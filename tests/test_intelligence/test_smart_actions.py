"""Tests for SmartActionHandler -- fuzzy matching, find_or_create, resolve, smart_create."""
import pytest
from unittest.mock import MagicMock, patch, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.errors import OdooClawError
from openclaw_odoo.intelligence.smart_actions import SmartActionHandler, _SENSITIVE_MODELS


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
    c.fields_get = MagicMock(return_value={})
    c.search_count = MagicMock(return_value=0)
    c.write = MagicMock()
    return c


@pytest.fixture
def handler(client):
    return SmartActionHandler(client)


# =============================================================
# find_or_create_partner
# =============================================================

class TestFindOrCreatePartner:
    def test_finds_existing_by_exact_name(self, handler, client):
        client.search_read.return_value = [
            {"id": 10, "name": "Acme Corp", "email": "info@acme.com"}
        ]
        result = handler.find_or_create_partner("Acme Corp")
        assert result["id"] == 10
        assert result["created"] is False

    def test_finds_existing_by_email(self, handler, client):
        client.search_read.side_effect = [
            [],  # exact name search
            [{"id": 20, "name": "Acme", "email": "info@acme.com"}],  # ilike
        ]
        result = handler.find_or_create_partner("info@acme.com")
        assert result["id"] == 20
        assert result["created"] is False

    def test_creates_when_not_found(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 99
        result = handler.find_or_create_partner("New Partner Inc")
        assert result["id"] == 99
        assert result["created"] is True
        client.create.assert_called_once()
        vals = client.create.call_args[0][1]
        assert vals["name"] == "New Partner Inc"

    def test_creates_company_with_email(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 50
        result = handler.find_or_create_partner(
            "Big Co", email="hello@big.co", is_company=True
        )
        vals = client.create.call_args[0][1]
        assert vals["email"] == "hello@big.co"
        assert vals["is_company"] is True


# =============================================================
# find_or_create_product
# =============================================================

class TestFindOrCreateProduct:
    def test_finds_existing(self, handler, client):
        client.search_read.return_value = [
            {"id": 5, "name": "Widget", "list_price": 25.0}
        ]
        result = handler.find_or_create_product("Widget")
        assert result["id"] == 5
        assert result["created"] is False

    def test_fuzzy_match(self, handler, client):
        client.search_read.side_effect = [
            [],  # exact
            [{"id": 6, "name": "Super Widget", "list_price": 30.0}],  # ilike
        ]
        result = handler.find_or_create_product("widget")
        assert result["id"] == 6
        assert result["created"] is False

    def test_creates_when_not_found(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 77
        result = handler.find_or_create_product("New Gadget", list_price=49.99)
        assert result["id"] == 77
        assert result["created"] is True
        vals = client.create.call_args[0][1]
        assert vals["name"] == "New Gadget"
        assert vals["list_price"] == 49.99


# =============================================================
# find_or_create_project
# =============================================================

class TestFindOrCreateProject:
    def test_finds_existing(self, handler, client):
        client.search_read.return_value = [
            {"id": 3, "name": "Website Redesign"}
        ]
        result = handler.find_or_create_project("Website Redesign")
        assert result["id"] == 3
        assert result["created"] is False

    def test_creates_when_not_found(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 15
        result = handler.find_or_create_project("New Project")
        assert result["id"] == 15
        assert result["created"] is True


# =============================================================
# resolve_department
# =============================================================

class TestResolveDepartment:
    def test_resolves_by_exact_name(self, handler, client):
        client.search_read.return_value = [
            {"id": 4, "name": "Engineering"}
        ]
        result = handler.resolve_department("Engineering")
        assert result == 4

    def test_resolves_by_fuzzy(self, handler, client):
        client.search_read.side_effect = [
            [],  # exact
            [{"id": 7, "name": "Engineering Department"}],  # ilike
        ]
        result = handler.resolve_department("engineering")
        assert result == 7

    def test_returns_none_when_not_found(self, handler, client):
        client.search_read.return_value = []
        result = handler.resolve_department("Nonexistent Dept")
        assert result is None


# =============================================================
# resolve_user
# =============================================================

class TestResolveUser:
    def test_resolves_by_name(self, handler, client):
        client.search_read.return_value = [
            {"id": 2, "name": "John Doe", "login": "john@example.com"}
        ]
        result = handler.resolve_user("John Doe")
        assert result == 2

    def test_resolves_by_login(self, handler, client):
        client.search_read.side_effect = [
            [],  # exact name
            [{"id": 3, "name": "Jane", "login": "jane@co.com"}],  # ilike
        ]
        result = handler.resolve_user("jane@co.com")
        assert result == 3

    def test_returns_none_when_not_found(self, handler, client):
        client.search_read.return_value = []
        result = handler.resolve_user("nobody")
        assert result is None


# =============================================================
# smart_create_quotation
# =============================================================

class TestSmartCreateQuotation:
    def test_resolves_partner_and_products(self, handler, client):
        # Partner lookup
        client.search_read.side_effect = [
            [{"id": 10, "name": "Acme", "email": ""}],  # find partner
            [{"id": 5, "name": "Widget", "list_price": 25.0}],  # find product 1
            [{"id": 6, "name": "Gadget", "list_price": 50.0}],  # find product 2
        ]
        client.create.return_value = 42
        result = handler.smart_create_quotation(
            partner="Acme",
            lines=[
                {"product": "Widget", "quantity": 3},
                {"product": "Gadget", "quantity": 1, "price_unit": 45.0},
            ],
        )
        assert result["id"] == 42
        assert "web_url" in result
        # Verify sale.order create call
        vals = client.create.call_args[0][1]
        assert vals["partner_id"] == 10
        assert len(vals["order_line"]) == 2

    def test_creates_partner_if_not_found(self, handler, client):
        client.search_read.side_effect = [
            [],  # partner exact - not found
            [],  # partner ilike - not found
            [{"id": 5, "name": "Widget", "list_price": 25.0}],  # product
        ]
        client.create.side_effect = [88, 42]  # partner create, then order create
        result = handler.smart_create_quotation(
            partner="Brand New Co",
            lines=[{"product": "Widget", "quantity": 1}],
        )
        # Should have created partner first, then order
        assert client.create.call_count == 2
        assert result["id"] == 42


# =============================================================
# smart_create_invoice
# =============================================================

class TestSmartCreateInvoice:
    def test_resolves_partner_and_creates(self, handler, client):
        client.search_read.side_effect = [
            [{"id": 10, "name": "Acme", "email": ""}],  # find partner
        ]
        client.create.return_value = 55
        result = handler.smart_create_invoice(
            partner="Acme",
            lines=[{"name": "Consulting", "quantity": 10, "price_unit": 150}],
        )
        assert result["id"] == 55
        vals = client.create.call_args[0][1]
        assert vals["partner_id"] == 10
        assert vals["move_type"] == "out_invoice"
        assert len(vals["invoice_line_ids"]) == 1


# =============================================================
# smart_create_purchase
# =============================================================

class TestSmartCreatePurchase:
    def test_resolves_partner_and_products(self, handler, client):
        client.search_read.side_effect = [
            [{"id": 10, "name": "Supplier Co", "email": ""}],  # partner
            [{"id": 5, "name": "Raw Material", "list_price": 10.0}],  # product
        ]
        client.create.return_value = 30
        result = handler.smart_create_purchase(
            partner="Supplier Co",
            lines=[{"product": "Raw Material", "quantity": 100}],
        )
        assert result["id"] == 30
        vals = client.create.call_args[0][1]
        assert vals["partner_id"] == 10
        assert len(vals["order_line"]) == 1


# =============================================================
# smart_create_task
# =============================================================

class TestSmartCreateTask:
    def test_resolves_project_and_user(self, handler, client):
        client.search_read.side_effect = [
            [{"id": 3, "name": "Website Redesign"}],  # project
            [{"id": 2, "name": "John Doe", "login": "john@co.com"}],  # user
        ]
        client.create.return_value = 88
        result = handler.smart_create_task(
            project="Website Redesign",
            name="Fix homepage",
            user="John Doe",
        )
        assert result["id"] == 88
        vals = client.create.call_args[0][1]
        assert vals["project_id"] == 3
        assert vals["user_ids"] == [2]
        assert vals["name"] == "Fix homepage"

    def test_creates_project_if_not_found(self, handler, client):
        client.search_read.side_effect = [
            [],  # project exact - not found
            [],  # project ilike - not found
        ]
        client.create.side_effect = [15, 88]  # project create, then task create
        result = handler.smart_create_task(
            project="New Project",
            name="First task",
        )
        assert client.create.call_count == 2

    def test_no_user(self, handler, client):
        client.search_read.return_value = [
            {"id": 3, "name": "Project X"}
        ]
        client.create.return_value = 88
        result = handler.smart_create_task(
            project="Project X", name="Solo task"
        )
        vals = client.create.call_args[0][1]
        assert "user_ids" not in vals


# =============================================================
# smart_create_lead
# =============================================================

class TestSmartCreateLead:
    def test_basic_lead(self, handler, client):
        client.create.return_value = 44
        result = handler.smart_create_lead(
            name="Interested in Enterprise Plan",
            contact_name="Alice",
            email="alice@startup.io",
        )
        assert result["id"] == 44
        vals = client.create.call_args[0][1]
        assert vals["name"] == "Interested in Enterprise Plan"
        assert vals["contact_name"] == "Alice"
        assert vals["email_from"] == "alice@startup.io"

    def test_lead_with_partner_resolve(self, handler, client):
        client.search_read.return_value = [
            {"id": 10, "name": "Acme", "email": "info@acme.com"}
        ]
        client.create.return_value = 45
        result = handler.smart_create_lead(
            name="Acme wants upgrade",
            partner="Acme",
        )
        vals = client.create.call_args[0][1]
        assert vals["partner_id"] == 10


# =============================================================
# smart_create_employee
# =============================================================

class TestSmartCreateEmployee:
    def test_resolves_department(self, handler, client):
        client.search_read.return_value = [
            {"id": 4, "name": "Engineering"}
        ]
        client.create.return_value = 33
        result = handler.smart_create_employee(
            name="Jane Smith",
            job_title="Software Engineer",
            department="Engineering",
        )
        assert result["id"] == 33
        vals = client.create.call_args[0][1]
        assert vals["department_id"] == 4
        assert vals["job_title"] == "Software Engineer"

    def test_no_department(self, handler, client):
        client.create.return_value = 34
        result = handler.smart_create_employee(
            name="Bob Builder",
            job_title="Contractor",
        )
        vals = client.create.call_args[0][1]
        assert "department_id" not in vals

    def test_department_not_found_auto_creates(self, handler, client):
        client.search_read.return_value = []
        # First create call: department auto-create returns 99
        # Second create call: employee create returns 35
        client.create.side_effect = [99, 35]
        result = handler.smart_create_employee(
            name="Eve",
            department="Nonexistent",
        )
        # Should have created the department first (auto_create=True)
        assert client.create.call_count == 2
        dept_call = client.create.call_args_list[0]
        assert dept_call[0][0] == "hr.department"
        assert dept_call[0][1] == {"name": "Nonexistent"}
        # Then created the employee with the new department_id
        emp_vals = client.create.call_args_list[1][0][1]
        assert emp_vals["department_id"] == 99


# =============================================================
# generic_find_or_create
# =============================================================

class TestGenericFindOrCreate:
    def test_finds_existing_record(self, handler, client):
        client.search_read.return_value = [
            {"id": 10, "license_plate": "KA-01-1234"}
        ]
        result = handler.generic_find_or_create(
            "x_fleet.vehicle", "KA-01-1234", name_field="license_plate"
        )
        assert result["id"] == 10
        assert result["created"] is False
        assert result["license_plate"] == "KA-01-1234"

    def test_creates_when_not_found(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 42
        result = handler.generic_find_or_create(
            "x_fleet.vehicle", "NEW-001", name_field="license_plate"
        )
        assert result["id"] == 42
        assert result["created"] is True
        assert result["license_plate"] == "NEW-001"
        client.create.assert_called_once_with(
            "x_fleet.vehicle", {"license_plate": "NEW-001"}
        )

    def test_creates_with_extra_values(self, handler, client):
        client.search_read.return_value = []
        client.create.return_value = 55
        result = handler.generic_find_or_create(
            "x_fleet.vehicle", "TRUCK-001",
            name_field="license_plate",
            extra_values={"driver_id": 5, "fuel_type": "diesel"},
        )
        assert result["id"] == 55
        assert result["created"] is True
        client.create.assert_called_once_with(
            "x_fleet.vehicle",
            {"license_plate": "TRUCK-001", "driver_id": 5, "fuel_type": "diesel"},
        )

    def test_default_name_field(self, handler, client):
        client.search_read.return_value = [
            {"id": 7, "name": "Widget"}
        ]
        result = handler.generic_find_or_create(
            "x_custom.model", "Widget"
        )
        assert result["id"] == 7
        assert result["created"] is False
        assert result["name"] == "Widget"

    def test_fuzzy_match_finds_existing(self, handler, client):
        # First call (exact) returns nothing, second call (ilike) finds it
        client.search_read.side_effect = [
            [],  # exact search
            [{"id": 20, "name": "Super Widget"}],  # ilike search
        ]
        result = handler.generic_find_or_create(
            "x_custom.model", "widget"
        )
        assert result["id"] == 20
        assert result["created"] is False

    def test_rejects_sensitive_model(self, handler, client):
        """generic_find_or_create must raise on sensitive models."""
        for model in [
            "res.users", "ir.cron", "ir.config_parameter",
            "ir.module.module", "ir.rule", "ir.model.access",
            "ir.ui.view", "ir.actions.server", "ir.mail_server",
            "base.automation",
        ]:
            with pytest.raises(OdooClawError, match="sensitive model"):
                handler.generic_find_or_create(model, "test")
        # Client should never be called
        client.search_read.assert_not_called()
        client.create.assert_not_called()

    def test_allows_non_sensitive_model(self, handler, client):
        """Normal models should pass through without error."""
        client.search_read.return_value = []
        client.create.return_value = 1
        result = handler.generic_find_or_create("product.product", "Widget")
        assert result["created"] is True

    def test_sensitive_models_set_completeness(self):
        """Verify the deny list contains all expected models."""
        expected = {
            "res.users", "ir.cron", "ir.config_parameter", "ir.module.module",
            "ir.rule", "ir.model.access", "ir.ui.view", "ir.actions.server",
            "ir.mail_server", "base.automation",
        }
        assert _SENSITIVE_MODELS == expected
