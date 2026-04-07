"""Integration tests -- end-to-end flows across modules with mocked OdooClient."""
import json
import pytest
from unittest.mock import MagicMock, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.modules import sales, partners, crm, accounting, inventory, projects, hr
from openclaw_odoo.intelligence.smart_actions import SmartActionHandler
from openclaw_odoo.interfaces.cli import build_parser, run_command


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c.execute = MagicMock()
    c.search_read = MagicMock(return_value=[])
    c.create = MagicMock(return_value=1)
    c.read = MagicMock(return_value=[])
    c.write = MagicMock(return_value=True)
    c.unlink = MagicMock(return_value=True)
    c.fields_get = MagicMock(return_value={
        "id": {"type": "integer", "string": "ID"},
        "name": {"type": "char", "string": "Name", "required": True},
        "state": {"type": "selection", "string": "Status"},
        "partner_id": {"type": "many2one", "string": "Partner"},
        "amount_total": {"type": "monetary", "string": "Total"},
    })
    c.search_count = MagicMock(return_value=0)
    return c


# =============================================================
# Flow 1: Quote-to-cash -- partner -> quotation -> confirm -> invoice
# =============================================================

class TestQuoteToCash:
    def test_full_flow(self, client):
        # Step 1: Create partner
        client.create.return_value = 10
        partner_result = partners.create_partner(
            client, "Acme Corp", email="info@acme.com", is_company=True
        )
        assert partner_result["id"] == 10

        # Step 2: Create quotation for that partner
        client.create.return_value = 42
        lines = [
            {"product_id": 1, "quantity": 5, "price_unit": 100.0},
            {"product_id": 2, "quantity": 3, "price_unit": 50.0},
        ]
        quote_result = sales.create_quotation(client, partner_id=10, lines=lines)
        assert quote_result["id"] == 42

        # Step 3: Confirm the order
        confirm_result = sales.confirm_order(client, order_id=42)
        assert confirm_result["success"] is True
        client.execute.assert_called_with("sale.order", "action_confirm", [42])

        # Step 4: Create invoice
        client.create.return_value = 100
        invoice_lines = [
            {"name": "Widget x5", "quantity": 5, "price_unit": 100.0},
            {"name": "Gadget x3", "quantity": 3, "price_unit": 50.0},
        ]
        invoice_result = accounting.create_invoice(client, partner_id=10, lines=invoice_lines)
        assert invoice_result["id"] == 100

        # Step 5: Post invoice
        accounting.post_invoice(client, invoice_id=100)
        client.execute.assert_called_with("account.move", "action_post", [100])


# =============================================================
# Flow 2: Smart actions -- name-based quotation creation
# =============================================================

class TestSmartQuotationFlow:
    def test_create_quotation_by_names(self, client):
        handler = SmartActionHandler(client)

        # Partner found by name
        client.search_read.side_effect = [
            [{"id": 10, "name": "Acme Corp", "email": "info@acme.com", "phone": ""}],
            [{"id": 5, "name": "Widget", "list_price": 100.0}],
            [{"id": 6, "name": "Gadget", "list_price": 50.0}],
        ]
        client.create.return_value = 42

        result = handler.smart_create_quotation(
            partner="Acme Corp",
            lines=[
                {"product": "Widget", "quantity": 5},
                {"product": "Gadget", "quantity": 3},
            ],
        )
        assert result["id"] == 42
        # Verify the create call had the right partner and line count
        vals = client.create.call_args[0][1]
        assert vals["partner_id"] == 10
        assert len(vals["order_line"]) == 2

    def test_creates_missing_partner_and_product(self, client):
        handler = SmartActionHandler(client)

        # Nothing found for partner or product
        client.search_read.return_value = []
        client.create.side_effect = [10, 5, 42]  # partner, product, order

        result = handler.smart_create_quotation(
            partner="New Customer",
            lines=[{"product": "New Widget", "quantity": 1}],
        )
        assert result["id"] == 42
        assert client.create.call_count == 3


# =============================================================
# Flow 3: CRM lead -> opportunity -> won
# =============================================================

class TestCRMLeadFlow:
    def test_lead_to_won(self, client):
        # Step 1: Create lead
        client.create.return_value = 20
        lead = crm.create_lead(
            client, "Interested in Enterprise",
            email_from="alice@startup.io",
        )
        assert lead["id"] == 20

        # Step 2: Create opportunity
        client.create.return_value = 30
        opp = crm.create_opportunity(
            client, "Enterprise Deal", partner_id=10,
            expected_revenue=50000,
        )
        assert opp["id"] == 30

        # Step 3: Mark as won
        won_result = crm.mark_won(client, lead_id=30)
        assert won_result["success"] is True
        client.execute.assert_called_with("crm.lead", "action_set_won", [30])


# =============================================================
# Flow 4: HR employee + project task assignment
# =============================================================

class TestHRProjectFlow:
    def test_employee_task_assignment(self, client):
        # Create employee
        client.create.return_value = 50
        emp = hr.create_employee(
            client, "Jane Smith", job_title="Developer", department_id=4
        )
        assert emp["id"] == 50

        # Create project
        client.create.return_value = 3
        proj = projects.create_project(client, "Website Redesign")
        assert proj["id"] == 3

        # Create task assigned to employee's user
        client.create.return_value = 88
        task = projects.create_task(
            client, project_id=3, name="Implement login page", user_ids=[50]
        )
        assert task["id"] == 88
        vals = client.create.call_args[0][1]
        assert vals["project_id"] == 3
        assert vals["user_ids"] == [50]


# =============================================================
# Flow 5: Smart task creation with name resolution
# =============================================================

class TestSmartTaskFlow:
    def test_create_task_resolves_names(self, client):
        handler = SmartActionHandler(client)

        client.search_read.side_effect = [
            [{"id": 3, "name": "Website Redesign"}],  # project found
            [{"id": 2, "name": "John Doe", "login": "john@co.com"}],  # user found
        ]
        client.create.return_value = 88

        result = handler.smart_create_task(
            project="Website Redesign",
            name="Fix authentication",
            user="John Doe",
        )
        assert result["id"] == 88
        vals = client.create.call_args[0][1]
        assert vals["project_id"] == 3
        assert vals["user_ids"] == [2]
        assert vals["name"] == "Fix authentication"


# =============================================================
# Flow 6: Inventory check + sales analytics
# =============================================================

class TestInventoryAnalyticsFlow:
    def test_check_stock_then_analyze_sales(self, client):
        # Check availability
        client.search_read.return_value = [
            {"quantity": 100.0, "reserved_quantity": 20.0}
        ]
        stock = inventory.check_availability(client, product_id=5)
        assert stock["available_qty"] == 100.0
        assert stock["reserved_qty"] == 20.0

        # Analyze sales
        client.search_read.side_effect = [
            [
                {"id": 1, "amount_total": 1000.0},
                {"id": 2, "amount_total": 2000.0},
            ],
            [
                {"product_id": [5, "Widget"], "price_subtotal": 3000.0,
                 "product_uom_qty": 15},
            ],
        ]
        analysis = sales.analyze_sales(client)
        assert analysis["total_orders"] == 2
        assert analysis["total_revenue"] == 3000.0
        assert len(analysis["top_products"]) == 1


# =============================================================
# Flow 7: CLI end-to-end
# =============================================================

class TestCLIIntegration:
    def test_cli_search_to_update_flow(self, client):
        # Search
        client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        parser = build_parser()
        args = parser.parse_args(["search", "res.partner", "--limit", "5"])
        results = run_command(args, client)
        assert len(results) == 1
        record_id = results[0]["id"]

        # Update found record
        args = parser.parse_args([
            "update", "res.partner", str(record_id),
            "--values", '{"phone": "+1-555-1234"}',
        ])
        result = run_command(args, client)
        assert result["success"] is True
        client.write.assert_called_with(
            "res.partner", [1], {"phone": "+1-555-1234"}
        )

    def test_cli_create_and_delete(self, client):
        client.create.return_value = 99
        parser = build_parser()

        # Create
        args = parser.parse_args([
            "create", "res.partner",
            "--values", '{"name": "Test Partner"}',
        ])
        result = run_command(args, client)
        assert result["id"] == 99

        # Delete (archive)
        args = parser.parse_args(["delete", "res.partner", "99"])
        result = run_command(args, client)
        assert result["success"] is True


# =============================================================
# Flow 8: Partner summary -- cross-module data aggregation
# =============================================================

class TestPartnerSummaryFlow:
    def test_partner_summary_aggregates_data(self, client):
        # Partner found
        client.search_read.return_value = [
            {"id": 10, "name": "Acme Corp", "email": "info@acme.com"}
        ]
        client.search_count.side_effect = [5, 3]  # sale orders, invoices
        # Revenue from confirmed orders
        client.search_read.side_effect = [
            [{"id": 10, "name": "Acme Corp", "email": "info@acme.com"}],
            [
                {"amount_total": 1000.0},
                {"amount_total": 2500.0},
                {"amount_total": 500.0},
            ],
        ]
        summary = partners.get_partner_summary(client, partner_id=10)
        assert summary["name"] == "Acme Corp"
        assert summary["sale_order_count"] == 5
        assert summary["invoice_count"] == 3
        assert summary["total_revenue"] == 4000.0
