"""Purchase module -- purchase orders, confirmations, analytics."""
from __future__ import annotations

from typing import Any, Optional

from ..client import OdooClient
from ..fields import select_smart_fields
from ..errors import OdooRecordNotFoundError

MODEL = "purchase.order"
LINE_MODEL = "purchase.order.line"

ORDER_FIELDS = [
    "name", "state", "partner_id", "date_order", "amount_total",
    "amount_untaxed", "amount_tax", "currency_id", "user_id",
]
LINE_FIELDS = [
    "product_id", "product_qty", "price_unit", "price_subtotal",
    "name", "product_uom_id",
]


def create_purchase_order(
    client: OdooClient,
    partner_id: int,
    lines: list[dict],
    **extra: Any,
) -> dict:
    """Create a purchase order with one or more order lines.

    Args:
        client: Authenticated OdooClient instance.
        partner_id: Vendor (res.partner) ID.
        lines: List of dicts, each with ``product_id``, ``quantity``,
            and optionally ``price_unit``.
        **extra: Additional fields to set on the purchase order
            (e.g. ``date_planned``, ``notes``).

    Returns:
        Dict with ``id`` and ``web_url`` of the created purchase order.
    """
    order_lines = []
    for line in lines:
        vals: dict[str, Any] = {
            "product_id": line["product_id"],
            "product_qty": line["quantity"],
        }
        if "price_unit" in line:
            vals["price_unit"] = line["price_unit"]
        order_lines.append((0, 0, vals))

    values = {"partner_id": partner_id, "order_line": order_lines, **extra}
    record_id = client.create(MODEL, values)
    return {
        "id": record_id,
        "web_url": client.web_url(MODEL, record_id),
    }


def confirm_purchase(client: OdooClient, order_id: int) -> dict:
    """Confirm a draft purchase order.

    Args:
        client: Authenticated OdooClient instance.
        order_id: ID of the purchase order to confirm.

    Returns:
        Dict with ``success`` flag and ``order_id``.
    """
    client.execute(MODEL, "button_confirm", [order_id])
    return {"success": True, "order_id": order_id}


def cancel_purchase(client: OdooClient, order_id: int) -> dict:
    """Cancel a purchase order.

    Args:
        client: Authenticated OdooClient instance.
        order_id: ID of the purchase order to cancel.

    Returns:
        Dict with ``success`` flag and ``order_id``.
    """
    client.execute(MODEL, "button_cancel", [order_id])
    return {"success": True, "order_id": order_id}


def get_purchase(
    client: OdooClient,
    order_id: int,
    smart_fields: bool = True,
) -> dict:
    """Retrieve a purchase order with its lines.

    Args:
        client: Authenticated OdooClient instance.
        order_id: ID of the purchase order to retrieve.
        smart_fields: If True, use smart field selection to limit
            the fields returned.

    Returns:
        Dict of order data including a ``lines`` key with order lines.

    Raises:
        OdooRecordNotFoundError: If the purchase order does not exist.
    """
    fields: Optional[list[str]] = None
    if smart_fields:
        fields_def = client.fields_get(MODEL)
        fields = select_smart_fields(fields_def)

    records = client.search_read(
        MODEL, domain=[["id", "=", order_id]], fields=fields, limit=1,
    )
    if not records:
        raise OdooRecordNotFoundError(
            f"Purchase order {order_id} not found", model=MODEL,
        )

    order = records[0]
    order["lines"] = client.search_read(
        LINE_MODEL,
        domain=[["order_id", "=", order_id]],
        fields=LINE_FIELDS,
    )
    return order


def search_purchases(
    client: OdooClient,
    domain: Optional[list] = None,
    limit: Optional[int] = None,
    **kwargs: Any,
) -> list[dict]:
    """Search purchase orders with optional filtering.

    Args:
        client: Authenticated OdooClient instance.
        domain: Odoo domain filter list (e.g. ``[["state", "=", "purchase"]]``).
        limit: Maximum number of records to return.
        **kwargs: Extra keyword arguments forwarded to ``search_read``
            (e.g. ``order``, ``offset``).

    Returns:
        List of purchase order dicts.
    """
    fields_def = client.fields_get(MODEL)
    fields = select_smart_fields(fields_def)
    return client.search_read(
        MODEL, domain=domain or [], fields=fields, limit=limit, **kwargs,
    )


def get_purchase_summary(
    client: OdooClient,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """Generate a purchase analytics summary.

    Computes totals across confirmed/done purchase orders and identifies
    top vendors by spend.

    Args:
        client: Authenticated OdooClient instance.
        date_from: ISO date string for the start of the period
            (inclusive, filters on ``date_order``).
        date_to: ISO date string for the end of the period
            (inclusive, filters on ``date_order``).

    Returns:
        Dict with ``total_orders``, ``total_amount``, ``average_order``,
        and ``top_vendors`` (list of dicts with ``vendor_name`` and
        ``total_amount``).
    """
    domain: list = [["state", "in", ["purchase", "done"]]]
    if date_from:
        domain.append(["date_order", ">=", date_from])
    if date_to:
        domain.append(["date_order", "<=", date_to])

    orders = client.search_read(
        MODEL, domain=domain,
        fields=["amount_total", "partner_id"], limit=0,
    )

    total_orders = len(orders)
    total_amount = sum(o.get("amount_total", 0) for o in orders)
    average_order = total_amount / total_orders if total_orders else 0.0

    # Aggregate by vendor
    vendor_map: dict[str, float] = {}
    for o in orders:
        pid = o.get("partner_id")
        if isinstance(pid, (list, tuple)) and len(pid) > 1:
            name = pid[1]
        else:
            name = str(pid)
        vendor_map[name] = vendor_map.get(name, 0.0) + o.get("amount_total", 0)

    top_vendors = sorted(
        [{"vendor_name": k, "total_amount": v} for k, v in vendor_map.items()],
        key=lambda x: x["total_amount"],
        reverse=True,
    )[:5]

    return {
        "total_orders": total_orders,
        "total_amount": total_amount,
        "average_order": average_order,
        "top_vendors": top_vendors,
    }
