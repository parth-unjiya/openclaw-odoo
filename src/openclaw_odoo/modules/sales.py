"""Sales module -- quotations, orders, analytics, and trends."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from ..client import OdooClient
from ..fields import select_smart_fields

MODEL = "sale.order"
LINE_MODEL = "sale.order.line"

ORDER_FIELDS = [
    "name", "state", "partner_id", "date_order", "amount_total",
    "amount_untaxed", "amount_tax", "currency_id", "user_id",
]
LINE_FIELDS = [
    "product_id", "product_uom_qty", "price_unit", "price_subtotal",
    "name", "product_uom_id",
]


def create_quotation(
    client: OdooClient,
    partner_id: int,
    lines: list[dict],
    **extra: Any,
) -> dict:
    """Create a sales quotation and return {id, web_url}.

    Args:
        client: OdooClient instance.
        partner_id: Customer partner ID.
        lines: List of dicts each with 'product_id', 'quantity', and optional 'price_unit'.
        **extra: Additional sale.order field values.

    Returns:
        Dict with 'id' and 'web_url' of the created quotation.
    """
    order_lines = []
    for line in lines:
        vals: dict[str, Any] = {
            "product_id": line["product_id"],
            "product_uom_qty": line["quantity"],
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


def confirm_order(client: OdooClient, order_id: int) -> dict:
    """Confirm a quotation, converting it to a sale order."""
    client.execute(MODEL, "action_confirm", [order_id])
    return {"success": True, "order_id": order_id}


def send_quotation_email(client: OdooClient, order_id: int) -> dict:
    """Send quotation by email using Odoo's mail wizard."""
    # Step 1: Get wizard action with context (includes template)
    wizard_action = client.execute(MODEL, "action_quotation_send", [order_id])
    ctx = wizard_action.get("context", {})

    # Step 2: Create mail.compose.message wizard
    wizard_vals = {
        "composition_mode": ctx.get("default_composition_mode", "comment"),
        "model": ctx.get("default_model", MODEL),
        "res_ids": ctx.get("default_res_ids", [order_id]),
        "template_id": ctx.get("default_template_id"),
        "email_layout_xmlid": ctx.get("default_email_layout_xmlid", ""),
    }
    wizard_id = client.execute("mail.compose.message", "create", wizard_vals)

    # Step 3: Send the email
    client.execute("mail.compose.message", "action_send_mail", [wizard_id])
    return {"success": True, "order_id": order_id, "message": "Quotation email sent"}


def cancel_order(client: OdooClient, order_id: int) -> dict:
    """Cancel a sale order."""
    client.execute(MODEL, "action_cancel", [order_id])
    return {"success": True, "order_id": order_id}


def get_order(
    client: OdooClient,
    order_id: int,
    smart_fields: bool = True,
) -> Optional[dict]:
    """Fetch a sale order by ID with its order lines.

    Args:
        client: OdooClient instance.
        order_id: Sale order record ID.
        smart_fields: If True, auto-select the most relevant fields.

    Returns:
        Order dict with nested 'lines' list, or None if not found.
    """
    fields: Optional[list[str]] = None
    if smart_fields:
        fields_def = client.fields_get(MODEL)
        fields = select_smart_fields(fields_def)

    records = client.search_read(
        MODEL, domain=[["id", "=", order_id]], fields=fields, limit=1,
    )
    if not records:
        return None

    order = records[0]
    order["lines"] = client.search_read(
        LINE_MODEL,
        domain=[["order_id", "=", order_id]],
        fields=LINE_FIELDS,
    )
    return order


def search_orders(
    client: OdooClient,
    domain: Optional[list] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Search sale orders with an optional domain filter.

    Args:
        client: OdooClient instance.
        domain: Odoo domain filter list.
        limit: Maximum records to return.

    Returns:
        List of order dicts with standard ORDER_FIELDS.
    """
    return client.search_read(
        MODEL, domain=domain or [], fields=ORDER_FIELDS, limit=limit,
    )


def get_order_lines(client: OdooClient, order_id: int) -> list[dict]:
    """Fetch all order lines for a given sale order."""
    return client.search_read(
        LINE_MODEL,
        domain=[["order_id", "=", order_id]],
        fields=LINE_FIELDS,
    )


def analyze_sales(
    client: OdooClient,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """Compute sales KPIs: total orders, revenue, avg order value, and top products.

    Args:
        client: OdooClient instance.
        date_from: Optional ISO date lower bound for date_order.
        date_to: Optional ISO date upper bound for date_order.

    Returns:
        Dict with total_orders, total_revenue, avg_order_value, top_products.
    """
    domain: list = [["state", "in", ["sale", "done"]]]
    if date_from:
        domain.append(["date_order", ">=", date_from])
    if date_to:
        domain.append(["date_order", "<=", date_to])

    orders = client.search_read(
        MODEL, domain=domain, fields=["amount_total"], limit=0,
    )

    total_orders = len(orders)
    total_revenue = sum(o.get("amount_total", 0) for o in orders)
    avg_order_value = total_revenue / total_orders if total_orders else 0.0

    # Gather order IDs for line-level product aggregation
    order_ids = [o.get("id") for o in orders if o.get("id")]
    line_domain: list = []
    if order_ids:
        line_domain = [["order_id", "in", order_ids]]
    elif date_from or date_to:
        line_domain = [["order_id.state", "in", ["sale", "done"]]]
        if date_from:
            line_domain.append(["order_id.date_order", ">=", date_from])
        if date_to:
            line_domain.append(["order_id.date_order", "<=", date_to])
    else:
        line_domain = [["order_id.state", "in", ["sale", "done"]]]

    lines = client.search_read(
        LINE_MODEL, domain=line_domain,
        fields=["product_id", "price_subtotal", "product_uom_qty"],
        limit=0,
    )
    top_products = _aggregate_products(lines, limit=5)

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "top_products": top_products,
    }


def get_sales_trend(
    client: OdooClient,
    months: int = 6,
) -> list[dict]:
    """Return monthly revenue trend for the last N months.

    Uses a single search_read call for the entire date range, then
    buckets orders by month in Python.

    Args:
        client: OdooClient instance.
        months: Number of months to look back (default 6).

    Returns:
        List of dicts with month, revenue, order_count, and change_pct.
    """
    today = date.today()

    # Build month boundaries for bucketing
    month_boundaries: list[tuple[date, date, str]] = []
    for i in range(months - 1, -1, -1):
        first = _month_offset(today, -i)
        if i > 0:
            last = _month_offset(today, -(i - 1)) - timedelta(days=1)
        else:
            last = today
        month_boundaries.append((first, last, first.strftime("%Y-%m")))

    # Single RPC: fetch all orders in the full date range
    range_start = month_boundaries[0][0]
    range_end = month_boundaries[-1][1]
    domain = [
        ["state", "in", ["sale", "done"]],
        ["date_order", ">=", range_start.isoformat()],
        ["date_order", "<=", range_end.isoformat()],
    ]
    all_orders = client.search_read(
        MODEL, domain=domain, fields=["amount_total", "date_order"], limit=0,
    )

    # Bucket orders by month label
    buckets: dict[str, list[dict]] = {label: [] for _, _, label in month_boundaries}
    for order in all_orders:
        raw_date = order.get("date_order", "")
        if not raw_date:
            continue
        # date_order may be a datetime string or date string; take first 7 chars for YYYY-MM
        order_month = str(raw_date)[:7]
        if order_month in buckets:
            buckets[order_month].append(order)

    # Build results in chronological order
    results: list[dict] = []
    for _, _, label in month_boundaries:
        month_orders = buckets[label]
        revenue = sum(o.get("amount_total", 0) for o in month_orders)
        order_count = len(month_orders)

        prev_revenue = results[-1]["revenue"] if results else None
        if prev_revenue is not None and prev_revenue > 0:
            change_pct = round((revenue - prev_revenue) / prev_revenue * 100, 1)
        elif prev_revenue is not None:
            change_pct = None
        else:
            change_pct = None

        results.append({
            "month": label,
            "revenue": revenue,
            "order_count": order_count,
            "change_pct": change_pct,
        })

    return results


def get_top_products(
    client: OdooClient,
    limit: int = 10,
    date_from: Optional[str] = None,
) -> list[dict]:
    """Rank products by revenue from confirmed sale order lines.

    Args:
        client: OdooClient instance.
        limit: Maximum number of products to return.
        date_from: Optional ISO date lower bound.

    Returns:
        List of dicts with product_id, product_name, total_revenue, total_qty.
    """
    domain: list = [["order_id.state", "in", ["sale", "done"]]]
    if date_from:
        domain.append(["order_id.date_order", ">=", date_from])

    lines = client.search_read(
        LINE_MODEL, domain=domain,
        fields=["product_id", "price_subtotal", "product_uom_qty"],
        limit=0,
    )
    return _aggregate_products(lines, limit=limit)


def _aggregate_products(lines: list[dict], limit: int = 10) -> list[dict]:
    product_map: dict[int, dict] = {}
    for line in lines:
        pid_data = line.get("product_id")
        if not pid_data:
            continue
        if isinstance(pid_data, (list, tuple)) and len(pid_data) > 1:
            pid, pname = pid_data[0], pid_data[1]
        else:
            pid, pname = pid_data, str(pid_data)

        if pid not in product_map:
            product_map[pid] = {
                "product_id": pid,
                "product_name": pname,
                "total_revenue": 0.0,
                "total_qty": 0,
            }
        product_map[pid]["total_revenue"] += line.get("price_subtotal", 0.0)
        product_map[pid]["total_qty"] += line.get("product_uom_qty", 0)

    ranked = sorted(
        product_map.values(), key=lambda p: p["total_revenue"], reverse=True,
    )
    return ranked[:limit]


def _month_offset(d: date, months: int) -> date:
    m = d.month + months
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, 1)
