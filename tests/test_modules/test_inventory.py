import pytest
from unittest.mock import MagicMock, patch, call
from openclaw_odoo.client import OdooClient
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.modules.inventory import (
    create_product,
    search_products,
    update_product,
    check_availability,
    get_stock_levels,
    get_low_stock,
    analyze_inventory_turnover,
    get_stock_valuation,
)


@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    c.create = MagicMock()
    c.write = MagicMock()
    c.search_read = MagicMock()
    c.web_url = MagicMock()
    return c


# --- create_product ---

class TestCreateProduct:
    def test_creates_product_and_returns_id_and_url(self, client):
        client.create.return_value = 42
        client.web_url.return_value = "http://localhost:8069/odoo/product.product/42"

        result = create_product(client, "Widget")

        client.create.assert_called_once_with(
            "product.product",
            {"name": "Widget", "list_price": 0, "type": "consu"},
        )
        client.web_url.assert_called_once_with("product.product", 42)
        assert result == {
            "id": 42,
            "web_url": "http://localhost:8069/odoo/product.product/42",
        }

    def test_passes_extra_fields(self, client):
        client.create.return_value = 10
        client.web_url.return_value = "http://localhost:8069/odoo/product.product/10"

        result = create_product(client, "Gadget", list_price=99.99, product_type="product", barcode="123")

        client.create.assert_called_once_with(
            "product.product",
            {"name": "Gadget", "list_price": 99.99, "type": "product", "barcode": "123"},
        )
        assert result["id"] == 10


# --- search_products ---

class TestSearchProducts:
    def test_search_with_query(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Widget"}]

        result = search_products(client, query="Widget")

        client.search_read.assert_called_once()
        args, kwargs = client.search_read.call_args
        assert args[0] == "product.product"
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert [["name", "ilike", "Widget"]] == domain
        assert result == [{"id": 1, "name": "Widget"}]

    def test_search_with_domain(self, client):
        client.search_read.return_value = []

        result = search_products(client, domain=[["type", "=", "product"]])

        args, kwargs = client.search_read.call_args
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert domain == [["type", "=", "product"]]

    def test_search_with_query_and_domain(self, client):
        client.search_read.return_value = []

        result = search_products(client, query="Widget", domain=[["type", "=", "product"]])

        args, kwargs = client.search_read.call_args
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["name", "ilike", "Widget"] in domain
        assert ["type", "=", "product"] in domain

    def test_search_with_limit(self, client):
        client.search_read.return_value = []

        search_products(client, limit=5)

        args, kwargs = client.search_read.call_args
        assert kwargs.get("limit") == 5

    def test_search_no_filters(self, client):
        client.search_read.return_value = [{"id": 1}]

        result = search_products(client)

        args, kwargs = client.search_read.call_args
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert domain == []


# --- update_product ---

class TestUpdateProduct:
    def test_updates_and_returns_success(self, client):
        client.write.return_value = True

        result = update_product(client, 42, name="New Name", list_price=19.99)

        client.write.assert_called_once_with("product.product", [42], {"name": "New Name", "list_price": 19.99})
        assert result == {"success": True, "id": 42}


# --- check_availability ---

class TestCheckAvailability:
    def test_sums_quantities(self, client):
        client.search_read.return_value = [
            {"id": 1, "quantity": 50.0, "reserved_quantity": 10.0},
            {"id": 2, "quantity": 30.0, "reserved_quantity": 5.0},
        ]

        result = check_availability(client, product_id=42)

        args, kwargs = client.search_read.call_args
        assert args[0] == "stock.quant"
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["product_id", "=", 42] in domain
        assert result["product_id"] == 42
        assert result["available_qty"] == 80.0
        assert result["reserved_qty"] == 15.0

    def test_with_warehouse_filter(self, client):
        client.search_read.return_value = [
            {"id": 1, "quantity": 20.0, "reserved_quantity": 3.0},
        ]

        result = check_availability(client, product_id=42, warehouse_id=1)

        args, kwargs = client.search_read.call_args
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["product_id", "=", 42] in domain
        assert ["warehouse_id", "=", 1] in domain
        assert result["available_qty"] == 20.0

    def test_no_stock_returns_zero(self, client):
        client.search_read.return_value = []

        result = check_availability(client, product_id=99)

        assert result["available_qty"] == 0.0
        assert result["reserved_qty"] == 0.0


# --- get_stock_levels ---

class TestGetStockLevels:
    def test_returns_products_with_stock(self, client):
        client.search_read.side_effect = [
            # First call: products
            [
                {"id": 1, "name": "Widget"},
                {"id": 2, "name": "Gadget"},
            ],
            # Second call: stock.quant
            [
                {"product_id": [1, "Widget"], "quantity": 50.0, "reserved_quantity": 10.0},
                {"product_id": [2, "Gadget"], "quantity": 20.0, "reserved_quantity": 0.0},
            ],
        ]

        result = get_stock_levels(client)

        assert len(result) == 2
        widget = next(r for r in result if r["product_id"] == 1)
        assert widget["name"] == "Widget"
        assert widget["qty_available"] == 50.0
        assert widget["qty_reserved"] == 10.0
        gadget = next(r for r in result if r["product_id"] == 2)
        assert gadget["qty_available"] == 20.0

    def test_with_warehouse_filter(self, client):
        client.search_read.side_effect = [
            [{"id": 1, "name": "Widget"}],
            [{"product_id": [1, "Widget"], "quantity": 10.0, "reserved_quantity": 0.0}],
        ]

        result = get_stock_levels(client, warehouse_id=1)

        # Second call (stock.quant) should include warehouse filter
        quant_call = client.search_read.call_args_list[1]
        args, kwargs = quant_call
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["warehouse_id", "=", 1] in domain

    def test_products_with_no_stock_show_zero(self, client):
        client.search_read.side_effect = [
            [{"id": 1, "name": "Widget"}, {"id": 2, "name": "NoStock"}],
            [{"product_id": [1, "Widget"], "quantity": 10.0, "reserved_quantity": 0.0}],
        ]

        result = get_stock_levels(client)

        nostock = next(r for r in result if r["product_id"] == 2)
        assert nostock["qty_available"] == 0.0
        assert nostock["qty_reserved"] == 0.0


# --- get_low_stock ---

class TestGetLowStock:
    def test_returns_low_stock_products(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Low Item", "qty_available": 3.0},
            {"id": 2, "name": "Critical", "qty_available": 0.0},
        ]

        result = get_low_stock(client, threshold=10)

        args, kwargs = client.search_read.call_args
        assert args[0] == "product.product"
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["qty_available", "<", 10] in domain
        assert len(result) == 2

    def test_default_threshold(self, client):
        client.search_read.return_value = []

        get_low_stock(client)

        args, kwargs = client.search_read.call_args
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["qty_available", "<", 10] in domain


# --- analyze_inventory_turnover ---

class TestAnalyzeInventoryTurnover:
    def test_calculates_turnover(self, client):
        client.search_read.side_effect = [
            # stock moves (outgoing)
            [
                {"product_id": [1, "Widget"], "product_qty": 100.0, "price_unit": 10.0},
                {"product_id": [1, "Widget"], "product_qty": 50.0, "price_unit": 10.0},
                {"product_id": [2, "Gadget"], "product_qty": 30.0, "price_unit": 20.0},
            ],
            # current stock (product.product)
            [
                {"id": 1, "name": "Widget", "qty_available": 40.0, "standard_price": 10.0},
                {"id": 2, "name": "Gadget", "qty_available": 25.0, "standard_price": 20.0},
            ],
        ]

        result = analyze_inventory_turnover(client)

        assert isinstance(result, list)
        widget = next(r for r in result if r["product_id"] == 1)
        # COGS = (100 + 50) * 10 = 1500
        # avg_inventory = 40 * 10 = 400 (current stock as proxy)
        # turnover = 1500 / 400 = 3.75
        assert widget["cogs"] == 1500.0
        assert widget["avg_inventory_value"] == 400.0
        assert widget["turnover_ratio"] == 3.75

    def test_with_date_range(self, client):
        client.search_read.side_effect = [[], []]

        analyze_inventory_turnover(client, date_from="2026-01-01", date_to="2026-03-01")

        move_call = client.search_read.call_args_list[0]
        args, kwargs = move_call
        domain = kwargs.get("domain", args[1] if len(args) > 1 else None)
        assert ["date", ">=", "2026-01-01"] in domain
        assert ["date", "<=", "2026-03-01"] in domain

    def test_zero_inventory_value(self, client):
        client.search_read.side_effect = [
            [{"product_id": [1, "Widget"], "product_qty": 10.0, "price_unit": 5.0}],
            [{"id": 1, "name": "Widget", "qty_available": 0.0, "standard_price": 5.0}],
        ]

        result = analyze_inventory_turnover(client)

        widget = next(r for r in result if r["product_id"] == 1)
        assert widget["turnover_ratio"] is None  # can't divide by zero


# --- get_stock_valuation ---

class TestGetStockValuation:
    def test_sums_valuation(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Widget", "qty_available": 100.0, "standard_price": 10.0},
            {"id": 2, "name": "Gadget", "qty_available": 50.0, "standard_price": 25.0},
        ]

        result = get_stock_valuation(client)

        assert result["total_valuation"] == 2250.0  # 100*10 + 50*25
        assert len(result["products"]) == 2
        widget = next(p for p in result["products"] if p["product_id"] == 1)
        assert widget["valuation"] == 1000.0

    def test_empty_stock(self, client):
        client.search_read.return_value = []

        result = get_stock_valuation(client)

        assert result["total_valuation"] == 0.0
        assert result["products"] == []
