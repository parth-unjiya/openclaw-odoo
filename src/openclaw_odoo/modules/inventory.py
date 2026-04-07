"""Inventory module -- product management, stock levels, and turnover analysis."""
from __future__ import annotations

from typing import Optional

from ..client import OdooClient


def create_product(client: OdooClient, name: str, list_price: float = 0,
                   product_type: str = "consu", **extra) -> dict:
    """Create a product and return {id, web_url}.

    Args:
        client: OdooClient instance.
        name: Product name.
        list_price: Sales price.
        product_type: Product type ('consu', 'service', or 'product').
        **extra: Additional product.product field values.

    Returns:
        Dict with 'id' and 'web_url' of the created product.
    """
    values = {"name": name, "list_price": list_price, "type": product_type, **extra}
    record_id = client.create("product.product", values)
    return {
        "id": record_id,
        "web_url": client.web_url("product.product", record_id),
    }


def search_products(client: OdooClient, query: Optional[str] = None,
                    domain: Optional[list] = None, limit: Optional[int] = None) -> list[dict]:
    """Search products by name (ilike) with optional domain filter.

    Args:
        client: OdooClient instance.
        query: Optional name search string.
        domain: Optional additional Odoo domain filter.
        limit: Maximum records to return.

    Returns:
        List of matching product dicts.
    """
    search_domain = domain or []
    if query:
        search_domain = [["name", "ilike", query]] + search_domain
    kwargs = {"domain": search_domain}
    if limit is not None:
        kwargs["limit"] = limit
    return client.search_read("product.product", **kwargs)


def update_product(client: OdooClient, product_id: int, **values) -> dict:
    """Update a product's fields."""
    client.write("product.product", [product_id], values)
    return {"success": True, "id": product_id}


def check_availability(client: OdooClient, product_id: int,
                        warehouse_id: Optional[int] = None) -> dict:
    """Check available and reserved stock quantities for a product.

    Args:
        client: OdooClient instance.
        product_id: Product record ID.
        warehouse_id: Optional warehouse to restrict the check.

    Returns:
        Dict with product_id, available_qty, and reserved_qty.
    """
    domain = [["product_id", "=", product_id]]
    if warehouse_id is not None:
        domain.append(["warehouse_id", "=", warehouse_id])
    quants = client.search_read(
        "stock.quant", domain=domain,
        fields=["quantity", "reserved_quantity"],
    )
    available = sum(q["quantity"] for q in quants)
    reserved = sum(q["reserved_quantity"] for q in quants)
    return {
        "product_id": product_id,
        "available_qty": available,
        "reserved_qty": reserved,
    }


def get_stock_levels(client: OdooClient, warehouse_id: Optional[int] = None,
                     limit: Optional[int] = None) -> list[dict]:
    """Get on-hand and reserved stock for all products.

    Args:
        client: OdooClient instance.
        warehouse_id: Optional warehouse filter.
        limit: Maximum number of products to return.

    Returns:
        List of dicts with product_id, name, qty_available, qty_reserved.
    """
    prod_kwargs: dict = {}
    if limit is not None:
        prod_kwargs["limit"] = limit
    else:
        prod_kwargs["limit"] = 0
    products = client.search_read(
        "product.product", domain=[], fields=["id", "name"], **prod_kwargs,
    )
    if not products:
        return []

    product_ids = [p["id"] for p in products]
    quant_domain = [["product_id", "in", product_ids]]
    if warehouse_id is not None:
        quant_domain.append(["warehouse_id", "=", warehouse_id])
    quants = client.search_read(
        "stock.quant", domain=quant_domain,
        fields=["product_id", "quantity", "reserved_quantity"],
        limit=0,
    )

    stock_by_product: dict[int, dict] = {}
    for q in quants:
        pid = q["product_id"][0] if isinstance(q["product_id"], list) else q["product_id"]
        if pid not in stock_by_product:
            stock_by_product[pid] = {"qty": 0.0, "reserved": 0.0}
        stock_by_product[pid]["qty"] += q["quantity"]
        stock_by_product[pid]["reserved"] += q["reserved_quantity"]

    result = []
    for p in products:
        stock = stock_by_product.get(p["id"], {"qty": 0.0, "reserved": 0.0})
        result.append({
            "product_id": p["id"],
            "name": p["name"],
            "qty_available": stock["qty"],
            "qty_reserved": stock["reserved"],
        })
    return result


def get_low_stock(client: OdooClient, threshold: int = 10) -> list[dict]:
    """Find products with available quantity below a threshold.

    Args:
        client: OdooClient instance.
        threshold: Minimum stock level (default 10).

    Returns:
        List of product dicts where qty_available < threshold.
    """
    return client.search_read(
        "product.product",
        domain=[["qty_available", "<", threshold]],
    )


def analyze_inventory_turnover(client: OdooClient, date_from: Optional[str] = None,
                                date_to: Optional[str] = None) -> list[dict]:
    """Compute inventory turnover ratio per product from outgoing stock moves.

    Args:
        client: OdooClient instance.
        date_from: Optional ISO date lower bound.
        date_to: Optional ISO date upper bound.

    Returns:
        List of dicts with product_id, name, cogs, avg_inventory_value, turnover_ratio.
    """
    move_domain = [["picking_code", "=", "outgoing"], ["state", "=", "done"]]
    if date_from:
        move_domain.append(["date", ">=", date_from])
    if date_to:
        move_domain.append(["date", "<=", date_to])

    moves = client.search_read(
        "stock.move", domain=move_domain,
        fields=["product_id", "product_qty", "price_unit"],
    )

    cogs_by_product: dict[int, float] = {}
    for m in moves:
        pid = m["product_id"][0] if isinstance(m["product_id"], list) else m["product_id"]
        cogs_by_product[pid] = cogs_by_product.get(pid, 0.0) + (m["product_qty"] * m["price_unit"])

    product_ids = list(cogs_by_product.keys())
    if not product_ids:
        return []

    products = client.search_read(
        "product.product",
        domain=[["id", "in", product_ids]],
        fields=["id", "name", "qty_available", "standard_price"],
    )

    result = []
    for p in products:
        cogs = cogs_by_product.get(p["id"], 0.0)
        avg_inv = p["qty_available"] * p["standard_price"]
        turnover = cogs / avg_inv if avg_inv > 0 else None
        result.append({
            "product_id": p["id"],
            "name": p["name"],
            "cogs": cogs,
            "avg_inventory_value": avg_inv,
            "turnover_ratio": turnover,
        })
    return result


def get_stock_valuation(client: OdooClient) -> dict:
    """Calculate total stock valuation (qty_available * standard_price) per product.

    Returns:
        Dict with total_valuation and a products list with per-item breakdown.
    """
    products = client.search_read(
        "product.product", domain=[],
        fields=["id", "name", "qty_available", "standard_price"],
        limit=0,
    )
    items = []
    total = 0.0
    for p in products:
        val = p["qty_available"] * p["standard_price"]
        total += val
        items.append({
            "product_id": p["id"],
            "name": p["name"],
            "qty_available": p["qty_available"],
            "standard_price": p["standard_price"],
            "valuation": val,
        })
    return {"total_valuation": total, "products": items}
