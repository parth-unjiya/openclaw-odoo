"""Tests for the purchase module."""
import pytest
from unittest.mock import MagicMock

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.errors import OdooRecordNotFoundError
from openclaw_odoo.modules.purchase import (
    create_purchase_order,
    confirm_purchase,
    cancel_purchase,
    get_purchase,
    search_purchases,
    get_purchase_summary,
)


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c.execute = MagicMock()
    c.search_read = MagicMock()
    c.create = MagicMock()
    c.read = MagicMock()
    c.fields_get = MagicMock()
    c.search_count = MagicMock()
    return c


# --- create_purchase_order ---

class TestCreatePurchaseOrder:
    def test_create_purchase_order(self, client):
        """Verify create called with correct model and vals."""
        client.create.return_value = 10
        lines = [{"product_id": 1, "quantity": 5}]
        result = create_purchase_order(client, partner_id=7, lines=lines)
        assert result["id"] == 10
        assert "web_url" in result
        assert "purchase.order" in result["web_url"]
        client.create.assert_called_once()
        call_args = client.create.call_args
        assert call_args[0][0] == "purchase.order"
        vals = call_args[0][1]
        assert vals["partner_id"] == 7
        assert len(vals["order_line"]) == 1
        line_vals = vals["order_line"][0][2]
        assert line_vals["product_id"] == 1
        assert line_vals["product_qty"] == 5

    def test_create_purchase_order_multiple_lines(self, client):
        """Verify multiple order lines are formatted correctly."""
        client.create.return_value = 20
        lines = [
            {"product_id": 1, "quantity": 10},
            {"product_id": 2, "quantity": 3, "price_unit": 25.50},
            {"product_id": 3, "quantity": 7},
        ]
        result = create_purchase_order(client, partner_id=15, lines=lines)
        assert result["id"] == 20
        vals = client.create.call_args[0][1]
        assert len(vals["order_line"]) == 3
        # Check Odoo one2many command format: (0, 0, {values})
        for cmd in vals["order_line"]:
            assert cmd[0] == 0
            assert cmd[1] == 0
        # Second line should have price_unit
        assert vals["order_line"][1][2]["price_unit"] == 25.50
        # First and third should not
        assert "price_unit" not in vals["order_line"][0][2]
        assert "price_unit" not in vals["order_line"][2][2]


# --- confirm_purchase ---

class TestConfirmPurchase:
    def test_confirm_purchase(self, client):
        """Verify execute called with button_confirm."""
        client.execute.return_value = True
        result = confirm_purchase(client, order_id=42)
        client.execute.assert_called_once_with(
            "purchase.order", "button_confirm", [42]
        )
        assert result["success"] is True
        assert result["order_id"] == 42


# --- cancel_purchase ---

class TestCancelPurchase:
    def test_cancel_purchase(self, client):
        """Verify execute called with button_cancel."""
        client.execute.return_value = True
        result = cancel_purchase(client, order_id=55)
        client.execute.assert_called_once_with(
            "purchase.order", "button_cancel", [55]
        )
        assert result["success"] is True
        assert result["order_id"] == 55


# --- get_purchase ---

class TestGetPurchase:
    def test_get_purchase(self, client):
        """Verify search_read + read for lines."""
        client.fields_get.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "state": {"type": "selection", "string": "State"},
            "partner_id": {"type": "many2one", "string": "Vendor"},
            "amount_total": {"type": "monetary", "string": "Total"},
        }
        client.search_read.side_effect = [
            [{"id": 42, "name": "PO042", "state": "purchase",
              "partner_id": [10, "Acme Supplies"], "amount_total": 2500.0}],
            [{"id": 1, "product_id": [7, "Raw Material"], "product_qty": 100,
              "price_unit": 25.0, "price_subtotal": 2500.0}],
        ]
        result = get_purchase(client, order_id=42, smart_fields=True)
        assert result["id"] == 42
        assert result["name"] == "PO042"
        assert "lines" in result
        assert len(result["lines"]) == 1
        client.fields_get.assert_called_once_with("purchase.order")

    def test_get_purchase_not_found(self, client):
        """Verify OdooRecordNotFoundError raised when order doesn't exist."""
        client.fields_get.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
        }
        client.search_read.return_value = []
        with pytest.raises(OdooRecordNotFoundError):
            get_purchase(client, order_id=999)


# --- search_purchases ---

class TestSearchPurchases:
    def test_search_purchases(self, client):
        """Basic search returns results."""
        client.fields_get.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "state": {"type": "selection", "string": "State"},
        }
        client.search_read.return_value = [
            {"id": 1, "name": "PO001"},
            {"id": 2, "name": "PO002"},
        ]
        result = search_purchases(client)
        assert len(result) == 2
        client.search_read.assert_called_once()
        call_args = client.search_read.call_args
        assert call_args[0][0] == "purchase.order"

    def test_search_purchases_with_domain(self, client):
        """Verify domain passed through to search_read."""
        client.fields_get.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
        }
        client.search_read.return_value = [{"id": 1, "name": "PO001"}]
        result = search_purchases(
            client,
            domain=[["state", "=", "purchase"]],
            limit=5,
        )
        call_args = client.search_read.call_args
        assert call_args[1]["domain"] == [["state", "=", "purchase"]]
        assert call_args[1]["limit"] == 5


# --- get_purchase_summary ---

class TestGetPurchaseSummary:
    def test_get_purchase_summary(self, client):
        """Verify aggregation logic for orders and top vendors."""
        client.search_read.return_value = [
            {"id": 1, "amount_total": 1000.0,
             "partner_id": [10, "Vendor A"]},
            {"id": 2, "amount_total": 2000.0,
             "partner_id": [11, "Vendor B"]},
            {"id": 3, "amount_total": 3000.0,
             "partner_id": [10, "Vendor A"]},
        ]
        result = get_purchase_summary(client)
        assert result["total_orders"] == 3
        assert result["total_amount"] == 6000.0
        assert result["average_order"] == 2000.0
        assert len(result["top_vendors"]) == 2
        # Vendor A should be first (4000 total)
        assert result["top_vendors"][0]["vendor_name"] == "Vendor A"
        assert result["top_vendors"][0]["total_amount"] == 4000.0
        assert result["top_vendors"][1]["vendor_name"] == "Vendor B"
        assert result["top_vendors"][1]["total_amount"] == 2000.0

    def test_get_purchase_summary_empty(self, client):
        """Verify zero handling when no orders exist."""
        client.search_read.return_value = []
        result = get_purchase_summary(client)
        assert result["total_orders"] == 0
        assert result["total_amount"] == 0.0
        assert result["average_order"] == 0.0
        assert result["top_vendors"] == []

    def test_get_purchase_summary_with_dates(self, client):
        """Verify date filters are included in domain."""
        client.search_read.return_value = [
            {"id": 1, "amount_total": 500.0,
             "partner_id": [10, "Vendor X"]},
        ]
        result = get_purchase_summary(
            client, date_from="2026-01-01", date_to="2026-01-31",
        )
        call_args = client.search_read.call_args
        domain = call_args[1]["domain"]
        date_filters = [d for d in domain if d[0] == "date_order"]
        assert len(date_filters) == 2
        assert result["total_orders"] == 1
        assert result["total_amount"] == 500.0
