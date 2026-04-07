"""Partners module -- CRUD, search, and analytics for res.partner."""
from __future__ import annotations
from typing import Any, Optional
from collections import defaultdict

from ..client import OdooClient
from ..errors import OdooRecordNotFoundError
from ..fields import select_smart_fields

MODEL = "res.partner"


def create_partner(client: OdooClient, name: str, email: Optional[str] = None,
                   phone: Optional[str] = None, is_company: bool = False,
                   **extra) -> dict:
    """Create a partner and return {id, web_url}.

    Args:
        client: OdooClient instance.
        name: Partner display name.
        email: Optional email address.
        phone: Optional phone number.
        is_company: True for company, False for individual.
        **extra: Additional field values passed to res.partner.

    Returns:
        Dict with 'id' and 'web_url' of the created partner.
    """
    values: dict[str, Any] = {"name": name, "is_company": is_company}
    if email is not None:
        values["email"] = email
    if phone is not None:
        values["phone"] = phone
    values.update(extra)
    record_id = client.create(MODEL, values)
    return {"id": record_id, "web_url": client.web_url(MODEL, record_id)}


def find_partner(client: OdooClient, query: str) -> list[dict]:
    """Search for partners by name, email, or phone (exact then fuzzy).

    Args:
        client: OdooClient instance.
        query: Search string matched against name, email, and phone.

    Returns:
        List of matching partner dicts.
    """
    # Try exact match first
    exact_domain = ["|", "|",
                    ["name", "=", query],
                    ["email", "=", query],
                    ["phone", "=", query]]
    results = client.search_read(MODEL, domain=exact_domain,
                                 fields=["name", "email", "phone"])
    if results:
        return results

    # Fall back to fuzzy (ilike) search
    ilike_domain = ["|", "|",
                    ["name", "ilike", query],
                    ["email", "ilike", query],
                    ["phone", "ilike", query]]
    return client.search_read(MODEL, domain=ilike_domain,
                              fields=["name", "email", "phone"])


def get_partner(client: OdooClient, partner_id: int,
                smart_fields: bool = True) -> dict:
    """Fetch a single partner by ID.

    Args:
        client: OdooClient instance.
        partner_id: Record ID of the partner.
        smart_fields: If True, auto-select the most relevant fields.

    Returns:
        Partner record dict.

    Raises:
        OdooRecordNotFoundError: If partner does not exist.
    """
    fields = None
    if smart_fields:
        fields_def = client.fields_get(MODEL)
        fields = select_smart_fields(fields_def)
    results = client.search_read(MODEL, domain=[["id", "=", partner_id]],
                                 fields=fields)
    if not results:
        raise OdooRecordNotFoundError(
            f"Partner {partner_id} not found", model=MODEL
        )
    return results[0]


def update_partner(client: OdooClient, partner_id: int, **values) -> dict:
    """Update a partner's fields and return {id, web_url}."""
    client.write(MODEL, [partner_id], values)
    return {"id": partner_id, "web_url": client.web_url(MODEL, partner_id)}


def delete_partner(client: OdooClient, partner_id: int) -> dict:
    """Archive a partner by setting active=False."""
    client.write(MODEL, [partner_id], {"active": False})
    return {"id": partner_id, "archived": True}


def get_partner_summary(client: OdooClient, partner_id: int) -> dict:
    """Get partner details enriched with sale order count, invoice count, and total revenue.

    Args:
        client: OdooClient instance.
        partner_id: Record ID of the partner.

    Returns:
        Partner dict with added sale_order_count, invoice_count, total_revenue.

    Raises:
        OdooRecordNotFoundError: If partner does not exist.
    """
    # Get partner data
    fields_def = client.fields_get(MODEL)
    fields = select_smart_fields(fields_def)
    partners = client.search_read(MODEL, domain=[["id", "=", partner_id]],
                                  fields=fields)
    if not partners:
        raise OdooRecordNotFoundError(
            f"Partner {partner_id} not found", model=MODEL
        )
    partner = partners[0]

    # Counts
    sale_count = client.search_count("sale.order",
                                     [["partner_id", "=", partner_id]])
    invoice_count = client.search_count("account.move",
                                        [["partner_id", "=", partner_id],
                                         ["move_type", "in", ["out_invoice", "out_refund"]]])

    # Total revenue from confirmed sale orders
    orders = client.search_read("sale.order",
                                domain=[["partner_id", "=", partner_id],
                                        ["state", "in", ["sale", "done"]]],
                                fields=["amount_total"],
                                limit=0)
    total_revenue = sum(o.get("amount_total", 0) for o in orders)

    partner["sale_order_count"] = sale_count
    partner["invoice_count"] = invoice_count
    partner["total_revenue"] = total_revenue
    return partner


def get_top_customers(client: OdooClient, limit: int = 10) -> list[dict]:
    """Rank customers by total revenue from confirmed sale orders.

    Args:
        client: OdooClient instance.
        limit: Maximum number of customers to return.

    Returns:
        List of dicts with partner_id, partner_name, total_revenue (descending).
    """
    orders = client.search_read("sale.order",
                                domain=[["state", "in", ["sale", "done"]]],
                                fields=["partner_id", "amount_total"],
                                limit=0)
    # Aggregate by partner
    revenue_by_partner: dict[int, dict] = defaultdict(
        lambda: {"partner_id": 0, "partner_name": "", "total_revenue": 0}
    )
    for order in orders:
        pid = order["partner_id"]
        if isinstance(pid, (list, tuple)):
            partner_id, partner_name = pid[0], pid[1]
        else:
            partner_id, partner_name = pid, ""
        entry = revenue_by_partner[partner_id]
        entry["partner_id"] = partner_id
        entry["partner_name"] = partner_name
        entry["total_revenue"] += order.get("amount_total", 0)

    sorted_customers = sorted(revenue_by_partner.values(),
                              key=lambda x: x["total_revenue"], reverse=True)
    return sorted_customers[:limit]
