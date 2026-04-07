"""Tests for the sales module."""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.modules.sales import (
    create_quotation,
    confirm_order,
    cancel_order,
    send_quotation_email,
    get_order,
    search_orders,
    get_order_lines,
    analyze_sales,
    get_sales_trend,
    get_top_products,
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


# --- create_quotation ---

class TestCreateQuotation:
    def test_basic(self, client):
        client.create.return_value = 42
        lines = [
            {"product_id": 1, "quantity": 5},
            {"product_id": 2, "quantity": 3, "price_unit": 19.99},
        ]
        result = create_quotation(client, partner_id=10, lines=lines)
        assert result["id"] == 42
        assert "web_url" in result
        assert "sale.order" in result["web_url"]
        # Verify create was called on sale.order
        client.create.assert_called_once()
        call_args = client.create.call_args
        assert call_args[0][0] == "sale.order"
        vals = call_args[0][1]
        assert vals["partner_id"] == 10
        assert len(vals["order_line"]) == 2

    def test_with_extra_fields(self, client):
        client.create.return_value = 99
        lines = [{"product_id": 1, "quantity": 1}]
        result = create_quotation(
            client, partner_id=5, lines=lines,
            note="Rush order", validity_date="2026-04-01"
        )
        vals = client.create.call_args[0][1]
        assert vals["note"] == "Rush order"
        assert vals["validity_date"] == "2026-04-01"

    def test_line_format(self, client):
        client.create.return_value = 1
        lines = [{"product_id": 7, "quantity": 2, "price_unit": 50.0}]
        create_quotation(client, partner_id=1, lines=lines)
        vals = client.create.call_args[0][1]
        line_cmd = vals["order_line"][0]
        # Odoo one2many command format: (0, 0, {values})
        assert line_cmd[0] == 0
        assert line_cmd[1] == 0
        line_vals = line_cmd[2]
        assert line_vals["product_id"] == 7
        assert line_vals["product_uom_qty"] == 2
        assert line_vals["price_unit"] == 50.0

    def test_line_without_price(self, client):
        client.create.return_value = 1
        lines = [{"product_id": 3, "quantity": 10}]
        create_quotation(client, partner_id=1, lines=lines)
        vals = client.create.call_args[0][1]
        line_vals = vals["order_line"][0][2]
        assert "price_unit" not in line_vals


# --- confirm_order ---

class TestConfirmOrder:
    def test_confirm(self, client):
        client.execute.return_value = True
        result = confirm_order(client, order_id=42)
        client.execute.assert_called_once_with(
            "sale.order", "action_confirm", [42]
        )
        assert result["success"] is True
        assert result["order_id"] == 42

    def test_confirm_returns_action(self, client):
        result = confirm_order(client, order_id=1)
        assert "order_id" in result


# --- cancel_order ---

class TestCancelOrder:
    def test_cancel(self, client):
        client.execute.return_value = True
        result = cancel_order(client, order_id=55)
        client.execute.assert_called_once_with(
            "sale.order", "action_cancel", [55]
        )
        assert result["success"] is True
        assert result["order_id"] == 55


# --- send_quotation_email ---

class TestSendQuotationEmail:
    def test_happy_path(self, client):
        """Full wizard flow: get action → create wizard → send mail."""
        wizard_action = {
            "context": {
                "default_composition_mode": "comment",
                "default_model": "sale.order",
                "default_res_ids": [42],
                "default_template_id": 7,
                "default_email_layout_xmlid": "mail.mail_notification_light",
            }
        }
        # execute call 1: action_quotation_send → wizard_action dict
        # execute call 2: mail.compose.message create → wizard_id 101
        # execute call 3: action_send_mail → True
        client.execute.side_effect = [wizard_action, 101, True]

        result = send_quotation_email(client, order_id=42)

        assert result["success"] is True
        assert result["order_id"] == 42
        assert result["message"] == "Quotation email sent"

        assert client.execute.call_count == 3

        # Step 1: fetch wizard action
        step1 = client.execute.call_args_list[0]
        assert step1 == call("sale.order", "action_quotation_send", [42])

        # Step 2: create mail.compose.message wizard
        step2 = client.execute.call_args_list[1]
        assert step2[0][0] == "mail.compose.message"
        assert step2[0][1] == "create"
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "sale.order"
        assert wizard_vals["res_ids"] == [42]
        assert wizard_vals["template_id"] == 7
        assert wizard_vals["email_layout_xmlid"] == "mail.mail_notification_light"

        # Step 3: send the email
        step3 = client.execute.call_args_list[2]
        assert step3 == call("mail.compose.message", "action_send_mail", [101])

    def test_uses_defaults_when_context_keys_missing(self, client):
        """When wizard action context is missing keys, defaults are applied."""
        wizard_action = {
            "context": {
                "default_template_id": 15,
            }
        }
        client.execute.side_effect = [wizard_action, 200, True]

        result = send_quotation_email(client, order_id=99)

        assert result["success"] is True
        assert result["order_id"] == 99

        step2 = client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        # Defaults from the function code
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "sale.order"
        assert wizard_vals["res_ids"] == [99]
        assert wizard_vals["template_id"] == 15
        assert wizard_vals["email_layout_xmlid"] == ""

    def test_empty_context_uses_all_defaults(self, client):
        """When wizard action returns empty context, all defaults kick in."""
        wizard_action = {"context": {}}
        client.execute.side_effect = [wizard_action, 50, True]

        result = send_quotation_email(client, order_id=10)

        assert result["success"] is True

        step2 = client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "sale.order"
        assert wizard_vals["res_ids"] == [10]
        assert wizard_vals["template_id"] is None
        assert wizard_vals["email_layout_xmlid"] == ""

    def test_no_context_key_in_action(self, client):
        """When wizard action has no 'context' key at all, .get returns {}."""
        wizard_action = {"type": "ir.actions.act_window"}
        client.execute.side_effect = [wizard_action, 77, True]

        result = send_quotation_email(client, order_id=5)

        assert result["success"] is True
        assert result["order_id"] == 5

        step2 = client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "sale.order"
        assert wizard_vals["res_ids"] == [5]
        assert wizard_vals["template_id"] is None

    def test_action_method_raises_propagates(self, client):
        """If the action method call raises, the error propagates."""
        client.execute.side_effect = Exception("RPC error")

        with pytest.raises(Exception, match="RPC error"):
            send_quotation_email(client, order_id=1)


# --- get_order ---

class TestGetOrder:
    def test_with_smart_fields(self, client):
        client.fields_get.return_value = {
            "id": {"type": "integer", "string": "ID"},
            "name": {"type": "char", "string": "Name"},
            "state": {"type": "selection", "string": "State"},
            "partner_id": {"type": "many2one", "string": "Partner"},
            "amount_total": {"type": "monetary", "string": "Total"},
        }
        client.search_read.side_effect = [
            [{"id": 42, "name": "SO042", "state": "sale",
              "partner_id": [10, "Acme"], "amount_total": 1500.0}],
            [{"id": 1, "product_id": [7, "Widget"], "product_uom_qty": 5,
              "price_unit": 300.0, "price_subtotal": 1500.0}],
        ]
        result = get_order(client, order_id=42, smart_fields=True)
        assert result["id"] == 42
        assert result["name"] == "SO042"
        assert "lines" in result
        assert len(result["lines"]) == 1
        client.fields_get.assert_called_once_with("sale.order")

    def test_without_smart_fields(self, client):
        client.search_read.side_effect = [
            [{"id": 42, "name": "SO042"}],
            [{"id": 1, "product_id": [7, "Widget"]}],
        ]
        result = get_order(client, order_id=42, smart_fields=False)
        assert result["id"] == 42
        client.fields_get.assert_not_called()

    def test_order_not_found(self, client):
        client.search_read.side_effect = [[], []]
        result = get_order(client, order_id=999)
        assert result is None


# --- search_orders ---

class TestSearchOrders:
    def test_basic_search(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "SO001"},
            {"id": 2, "name": "SO002"},
        ]
        result = search_orders(client)
        assert len(result) == 2
        client.search_read.assert_called_once()
        call_args = client.search_read.call_args
        assert call_args[0][0] == "sale.order"

    def test_with_domain_and_limit(self, client):
        client.search_read.return_value = [{"id": 1, "name": "SO001"}]
        result = search_orders(
            client,
            domain=[["state", "=", "sale"]],
            limit=5,
        )
        call_args = client.search_read.call_args
        assert call_args[1]["domain"] == [["state", "=", "sale"]]
        assert call_args[1]["limit"] == 5


# --- get_order_lines ---

class TestGetOrderLines:
    def test_basic(self, client):
        client.search_read.return_value = [
            {"id": 1, "product_id": [7, "Widget"], "product_uom_qty": 5},
            {"id": 2, "product_id": [8, "Gadget"], "product_uom_qty": 3},
        ]
        result = get_order_lines(client, order_id=42)
        assert len(result) == 2
        client.search_read.assert_called_once()
        call_args = client.search_read.call_args
        assert call_args[0][0] == "sale.order.line"
        assert call_args[1]["domain"] == [["order_id", "=", 42]]


# --- analyze_sales ---

class TestAnalyzeSales:
    def test_basic_analysis(self, client):
        client.search_read.return_value = [
            {"id": 1, "amount_total": 1000.0,
             "order_line": [1, 2]},
            {"id": 2, "amount_total": 2000.0,
             "order_line": [3]},
            {"id": 3, "amount_total": 3000.0,
             "order_line": [4, 5]},
        ]
        # For top products call
        client.search_read.side_effect = [
            # First call: confirmed orders
            [
                {"id": 1, "amount_total": 1000.0},
                {"id": 2, "amount_total": 2000.0},
                {"id": 3, "amount_total": 3000.0},
            ],
            # Second call: order lines for top products
            [
                {"product_id": [7, "Widget"], "price_subtotal": 3000.0,
                 "product_uom_qty": 10},
                {"product_id": [8, "Gadget"], "price_subtotal": 2000.0,
                 "product_uom_qty": 5},
                {"product_id": [7, "Widget"], "price_subtotal": 1000.0,
                 "product_uom_qty": 3},
            ],
        ]
        result = analyze_sales(client)
        assert result["total_orders"] == 3
        assert result["total_revenue"] == 6000.0
        assert result["avg_order_value"] == 2000.0
        assert "top_products" in result

    def test_with_date_range(self, client):
        client.search_read.side_effect = [
            [{"id": 1, "amount_total": 500.0}],
            [{"product_id": [1, "P1"], "price_subtotal": 500.0,
              "product_uom_qty": 2}],
        ]
        result = analyze_sales(
            client, date_from="2026-01-01", date_to="2026-01-31"
        )
        # Verify the domain includes date filters
        first_call = client.search_read.call_args_list[0]
        domain = first_call[1]["domain"]
        date_filters = [d for d in domain if d[0] == "date_order"]
        assert len(date_filters) == 2

    def test_no_orders(self, client):
        client.search_read.side_effect = [[], []]
        result = analyze_sales(client)
        assert result["total_orders"] == 0
        assert result["total_revenue"] == 0.0
        assert result["avg_order_value"] == 0.0
        assert result["top_products"] == []


# --- get_sales_trend ---

class TestGetSalesTrend:
    @staticmethod
    def _month_offset(d, months):
        m = d.month + months
        y = d.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        return date(y, m, 1)

    def test_basic_trend(self, client):
        today = date.today()
        # Build month labels matching the production _month_offset logic
        month_labels = []
        for i in range(5, -1, -1):
            first = self._month_offset(today, -i)
            month_labels.append(first.strftime("%Y-%m"))

        # Single batch call returns all orders with date_order
        client.search_read.return_value = [
            {"amount_total": 1000.0, "date_order": f"{month_labels[0]}-10"},
            {"amount_total": 2000.0, "date_order": f"{month_labels[0]}-20"},
            {"amount_total": 1500.0, "date_order": f"{month_labels[1]}-15"},
            {"amount_total": 2000.0, "date_order": f"{month_labels[2]}-05"},
            {"amount_total": 500.0, "date_order": f"{month_labels[2]}-25"},
            {"amount_total": 3000.0, "date_order": f"{month_labels[4]}-12"},
            {"amount_total": 1000.0, "date_order": f"{month_labels[5]}-01"},
            {"amount_total": 1000.0, "date_order": f"{month_labels[5]}-20"},
        ]
        result = get_sales_trend(client, months=6)
        assert len(result) == 6
        for entry in result:
            assert "month" in entry
            assert "revenue" in entry
            assert "order_count" in entry
            assert "change_pct" in entry
        # First month should have None change_pct (no prior month)
        assert result[0]["change_pct"] is None
        # Only 1 search_read call (batch)
        assert client.search_read.call_count == 1

    def test_change_pct_calculation(self, client):
        today = date.today()
        m1_label = self._month_offset(today, -1).strftime("%Y-%m")
        m2_label = self._month_offset(today, 0).strftime("%Y-%m")

        # Single batch: first month 1000, second month 1500 => 50% change
        client.search_read.return_value = [
            {"amount_total": 1000.0, "date_order": f"{m1_label}-15"},
            {"amount_total": 1500.0, "date_order": f"{m2_label}-15"},
        ]
        result = get_sales_trend(client, months=2)
        assert result[1]["change_pct"] == 50.0

    def test_single_month(self, client):
        today = date.today()
        month_label = today.strftime("%Y-%m")
        # Single batch for 1 month
        client.search_read.return_value = [
            {"amount_total": 500.0, "date_order": f"{month_label}-10"},
        ]
        result = get_sales_trend(client, months=1)
        assert len(result) == 1
        assert result[0]["revenue"] == 500.0
        assert result[0]["change_pct"] is None


# --- get_top_products ---

class TestGetTopProducts:
    def test_basic(self, client):
        client.search_read.return_value = [
            {"product_id": [7, "Widget"], "price_subtotal": 3000.0,
             "product_uom_qty": 10},
            {"product_id": [8, "Gadget"], "price_subtotal": 2000.0,
             "product_uom_qty": 5},
            {"product_id": [7, "Widget"], "price_subtotal": 1000.0,
             "product_uom_qty": 3},
        ]
        result = get_top_products(client, limit=10)
        assert len(result) == 2
        # Widget should be first (4000 total revenue)
        assert result[0]["product_id"] == 7
        assert result[0]["product_name"] == "Widget"
        assert result[0]["total_revenue"] == 4000.0
        assert result[0]["total_qty"] == 13
        # Gadget second
        assert result[1]["product_id"] == 8
        assert result[1]["total_revenue"] == 2000.0

    def test_with_date_filter(self, client):
        client.search_read.return_value = []
        get_top_products(client, limit=5, date_from="2026-01-01")
        call_args = client.search_read.call_args
        domain = call_args[1]["domain"]
        has_date_filter = any(
            d[0] == "order_id.date_order" for d in domain
        )
        assert has_date_filter

    def test_respects_limit(self, client):
        client.search_read.return_value = [
            {"product_id": [i, f"P{i}"], "price_subtotal": float(100 * i),
             "product_uom_qty": i}
            for i in range(1, 20)
        ]
        result = get_top_products(client, limit=3)
        assert len(result) == 3

    def test_empty(self, client):
        client.search_read.return_value = []
        result = get_top_products(client)
        assert result == []
