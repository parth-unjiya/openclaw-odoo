"""Tests for the OpenClaw skill interface -- stdin/stdout JSON bridge."""
import json
import pytest
from io import StringIO
from unittest.mock import MagicMock, patch

from openclaw_odoo.interfaces.openclaw_skill import route_action


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.search_read = MagicMock(return_value=[])
    client.search_count = MagicMock(return_value=0)
    client.create = MagicMock(return_value=1)
    client.write = MagicMock(return_value=True)
    client.unlink = MagicMock(return_value=True)
    client.read = MagicMock(return_value=[{}])
    client.execute = MagicMock(return_value=True)
    client.fields_get = MagicMock(return_value={})
    client.web_url = MagicMock(return_value="http://localhost:8069/odoo/res.partner/1")
    return client


# =============================================================
# Partners
# =============================================================

class TestPartnerActions:
    def test_create_partner(self, mock_client):
        result = route_action(mock_client, "create_partner", {"name": "Acme Corp"})
        assert result["id"] == 1
        mock_client.create.assert_called_once()

    def test_find_partner(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        result = route_action(mock_client, "find_partner", {"query": "Acme"})
        assert isinstance(result, list)
        assert result[0]["name"] == "Acme"

    def test_get_partner(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        result = route_action(mock_client, "get_partner", {"partner_id": 1})
        assert result["id"] == 1

    def test_update_partner(self, mock_client):
        result = route_action(mock_client, "update_partner", {"partner_id": 1, "email": "a@b.com"})
        assert result["id"] == 1

    def test_delete_partner(self, mock_client):
        result = route_action(mock_client, "delete_partner", {"partner_id": 1})
        assert result["archived"] is True

    def test_get_top_customers(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_top_customers", {})
        assert isinstance(result, list)


# =============================================================
# Sales
# =============================================================

class TestSalesActions:
    def test_create_quotation(self, mock_client):
        result = route_action(mock_client, "create_quotation", {
            "partner_id": 1,
            "lines": [{"product_id": 1, "quantity": 5}],
        })
        assert result["id"] == 1

    def test_confirm_order(self, mock_client):
        result = route_action(mock_client, "confirm_order", {"order_id": 1})
        assert result["success"] is True

    def test_cancel_order(self, mock_client):
        result = route_action(mock_client, "cancel_order", {"order_id": 1})
        assert result["success"] is True

    def test_get_order(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "SO001"}]
        result = route_action(mock_client, "get_order", {"order_id": 1})
        assert result["id"] == 1

    def test_search_orders(self, mock_client):
        result = route_action(mock_client, "search_orders", {})
        assert isinstance(result, list)

    def test_analyze_sales(self, mock_client):
        mock_client.search_read.side_effect = [[], []]
        result = route_action(mock_client, "analyze_sales", {})
        assert "total_orders" in result

    def test_get_sales_trend(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_sales_trend", {})
        assert isinstance(result, list)


# =============================================================
# CRM
# =============================================================

class TestCRMActions:
    def test_create_lead(self, mock_client):
        result = route_action(mock_client, "create_lead", {"name": "New Lead"})
        assert result["id"] == 1

    def test_create_opportunity(self, mock_client):
        result = route_action(mock_client, "create_opportunity", {
            "name": "Big Deal", "partner_id": 1,
        })
        assert result["id"] == 1

    def test_get_pipeline(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_pipeline", {})
        assert isinstance(result, list)

    def test_move_stage(self, mock_client):
        result = route_action(mock_client, "move_stage", {"lead_id": 1, "stage_id": 2})
        assert result["success"] is True

    def test_mark_won(self, mock_client):
        result = route_action(mock_client, "mark_won", {"lead_id": 1})
        assert result["success"] is True

    def test_mark_lost(self, mock_client):
        result = route_action(mock_client, "mark_lost", {"lead_id": 1})
        assert result["success"] is True

    def test_analyze_pipeline(self, mock_client):
        mock_client.search_count.return_value = 0
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "analyze_pipeline", {})
        assert "total_leads" in result

    def test_get_forecast(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_forecast", {})
        assert "weighted_revenue" in result


# =============================================================
# Inventory
# =============================================================

class TestInventoryActions:
    def test_create_product(self, mock_client):
        result = route_action(mock_client, "create_product", {"name": "Widget"})
        assert result["id"] == 1

    def test_search_products(self, mock_client):
        result = route_action(mock_client, "search_products", {"query": "Widget"})
        assert isinstance(result, list)

    def test_check_availability(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "check_availability", {"product_id": 1})
        assert "available_qty" in result

    def test_get_stock_levels(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_stock_levels", {})
        assert isinstance(result, list)

    def test_get_low_stock(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_low_stock", {})
        assert isinstance(result, list)

    def test_get_stock_valuation(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_stock_valuation", {})
        assert "total_valuation" in result


# =============================================================
# Accounting
# =============================================================

class TestAccountingActions:
    def test_create_invoice(self, mock_client):
        result = route_action(mock_client, "create_invoice", {
            "partner_id": 1,
            "lines": [{"price_unit": 100, "quantity": 2, "name": "Service"}],
        })
        assert result["id"] == 1

    def test_post_invoice(self, mock_client):
        route_action(mock_client, "post_invoice", {"invoice_id": 1})
        mock_client.execute.assert_called()

    def test_register_payment(self, mock_client):
        mock_client.search_read.return_value = [
            {"amount_residual": 100, "state": "posted",
             "move_type": "out_invoice", "partner_id": [1, "Acme"]}
        ]
        result = route_action(mock_client, "register_payment", {"invoice_id": 1})
        assert result["success"] is True
        assert "invoice_id" in result

    def test_get_unpaid_invoices(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_unpaid_invoices", {})
        assert isinstance(result, list)

    def test_get_overdue_invoices(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_overdue_invoices", {})
        assert isinstance(result, list)

    def test_analyze_financial_ratios(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "analyze_financial_ratios", {})
        assert "current_ratio" in result

    def test_get_aging_report(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_aging_report", {})
        assert "0-30" in result


# =============================================================
# HR
# =============================================================

class TestHRActions:
    def test_create_employee(self, mock_client):
        result = route_action(mock_client, "create_employee", {"name": "John Doe"})
        assert result["id"] == 1

    def test_checkin(self, mock_client):
        result = route_action(mock_client, "checkin", {"employee_id": 1})
        assert "check_in" in result

    def test_checkout(self, mock_client):
        mock_client.search_read.return_value = [{"id": 10, "check_in": "2026-03-06 08:00:00"}]
        result = route_action(mock_client, "checkout", {"employee_id": 1})
        assert "check_out" in result

    def test_get_attendance(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_attendance", {})
        assert isinstance(result, list)

    def test_request_leave(self, mock_client):
        result = route_action(mock_client, "request_leave", {
            "employee_id": 1, "leave_type_id": 1,
            "date_from": "2026-03-10", "date_to": "2026-03-11",
        })
        assert result["id"] == 1

    def test_get_leaves(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_leaves", {})
        assert isinstance(result, list)

    def test_get_headcount_summary(self, mock_client):
        mock_client.search_count.return_value = 10
        mock_client.execute.return_value = []
        result = route_action(mock_client, "get_headcount_summary", {})
        assert "total_employees" in result


# =============================================================
# Projects
# =============================================================

class TestProjectActions:
    def test_create_project(self, mock_client):
        result = route_action(mock_client, "create_project", {"name": "My Project"})
        assert result["id"] == 1

    def test_create_task(self, mock_client):
        result = route_action(mock_client, "create_task", {
            "project_id": 1, "name": "Task 1",
        })
        assert result["id"] == 1

    def test_update_task(self, mock_client):
        result = route_action(mock_client, "update_task", {"task_id": 1, "name": "Updated"})
        assert result["success"] is True

    def test_search_tasks(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "search_tasks", {})
        assert isinstance(result, list)

    def test_log_timesheet(self, mock_client):
        mock_client.read.return_value = [{"project_id": [1, "P1"]}]
        result = route_action(mock_client, "log_timesheet", {
            "task_id": 1, "hours": 2.5, "description": "Coding",
        })
        assert result["id"] == 1

    def test_get_project_summary(self, mock_client):
        mock_client.search_count.return_value = 5
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "get_project_summary", {"project_id": 1})
        assert "task_count" in result

    def test_create_ticket(self, mock_client):
        result = route_action(mock_client, "create_ticket", {"name": "Bug Report"})
        assert result["id"] == 1


# =============================================================
# Smart Actions
# =============================================================

class TestSmartActions:
    def test_smart_create_quotation(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        result = route_action(mock_client, "smart_create_quotation", {
            "partner": "Acme",
            "lines": [{"product": "Widget", "quantity": 10}],
        })
        assert result["id"] == 1

    def test_smart_create_invoice(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        result = route_action(mock_client, "smart_create_invoice", {
            "partner": "Acme",
            "lines": [{"name": "Consulting", "price_unit": 500, "quantity": 1}],
        })
        assert result["id"] == 1

    def test_smart_create_lead(self, mock_client):
        result = route_action(mock_client, "smart_create_lead", {
            "name": "Hot Lead", "email": "hot@lead.com",
        })
        assert result["id"] == 1

    def test_smart_create_task(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "My Project"}]
        result = route_action(mock_client, "smart_create_task", {
            "project": "My Project", "name": "New task",
        })
        assert result["id"] == 1

    def test_smart_create_employee(self, mock_client):
        result = route_action(mock_client, "smart_create_employee", {
            "name": "Jane Doe", "job_title": "Engineer",
        })
        assert result["id"] == 1


# =============================================================
# Analytics Dashboards
# =============================================================

class TestDashboards:
    def test_sales_dashboard(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "sales_dashboard", {})
        assert "summary" in result

    def test_financial_dashboard(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "financial_dashboard", {})
        assert "ratios" in result

    def test_inventory_dashboard(self, mock_client):
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "inventory_dashboard", {})
        assert "valuation" in result

    def test_hr_dashboard(self, mock_client):
        mock_client.search_count.return_value = 0
        mock_client.search_read.return_value = []
        mock_client.execute.return_value = []
        result = route_action(mock_client, "hr_dashboard", {})
        assert "headcount" in result

    def test_pipeline_dashboard(self, mock_client):
        mock_client.search_count.return_value = 0
        mock_client.search_read.return_value = []
        result = route_action(mock_client, "pipeline_dashboard", {})
        assert "pipeline" in result

    def test_full_dashboard(self, mock_client):
        mock_client.search_count.return_value = 0
        mock_client.search_read.return_value = []
        mock_client.execute.return_value = []
        result = route_action(mock_client, "full_dashboard", {})
        assert "sales" in result
        assert "financial" in result


# =============================================================
# Generic CRUD
# =============================================================

class TestGenericActions:
    def test_search(self, mock_client):
        result = route_action(mock_client, "search", {"model": "res.partner"})
        assert isinstance(result, list)

    def test_create(self, mock_client):
        result = route_action(mock_client, "create", {
            "model": "res.partner", "values": {"name": "Test"},
        })
        assert result["id"] == 1

    def test_update(self, mock_client):
        result = route_action(mock_client, "update", {
            "model": "res.partner", "record_id": 1, "values": {"name": "Updated"},
        })
        assert result["success"] is True

    def test_delete(self, mock_client):
        result = route_action(mock_client, "delete", {
            "model": "res.partner", "record_id": 1,
        })
        assert result["success"] is True

    def test_execute(self, mock_client):
        mock_client.execute.return_value = True
        result = route_action(mock_client, "execute", {
            "model": "sale.order", "method": "action_confirm", "args": [[1]],
        })
        assert result is True

    def test_fields(self, mock_client):
        mock_client.fields_get.return_value = {"name": {"type": "char"}}
        result = route_action(mock_client, "fields", {"model": "res.partner"})
        assert "name" in result

    def test_batch(self, mock_client):
        mock_client.execute.return_value = True
        result = route_action(mock_client, "batch", {
            "operations": [
                {"model": "res.partner", "method": "search_read", "args": [], "kwargs": {}},
            ],
        })
        assert "results" in result


# =============================================================
# Error handling
# =============================================================

class TestErrorHandling:
    def test_unknown_action(self, mock_client):
        result = route_action(mock_client, "nonexistent_action", {})
        assert result["error"] is True
        assert "Unknown action" in result["message"]

    def test_exception_in_action(self, mock_client):
        mock_client.create.side_effect = Exception("Odoo exploded")
        result = route_action(mock_client, "create_partner", {"name": "Fail"})
        assert result["error"] is True
        assert "Odoo exploded" in result["message"]


# =============================================================
# Dynamic registry routing
# =============================================================

class TestDynamicRegistryRouting:
    def test_auto_action_dispatched_via_registry(self, mock_client):
        """Auto-generated actions from the registry are accessible via route_action."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        # Save original registry
        original = skill_mod._registry

        try:
            # Set up a fake registry with one auto-action
            from unittest.mock import MagicMock
            fake_registry = MagicMock()
            fake_registry.get_auto_actions.return_value = {
                "search_fleet_vehicles": lambda domain=None, **kw: [{"id": 1, "name": "Truck"}],
            }
            skill_mod._registry = fake_registry

            result = route_action(mock_client, "search_fleet_vehicles", {})
            assert isinstance(result, list)
            assert result[0]["name"] == "Truck"
        finally:
            skill_mod._registry = original

    def test_builtin_actions_take_priority_over_auto(self, mock_client):
        """Builtin module actions are dispatched before auto-generated ones."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        original = skill_mod._registry

        try:
            fake_registry = MagicMock()
            # Even if registry has a "create_partner" auto-action, the builtin should win
            fake_registry.get_auto_actions.return_value = {
                "create_partner": lambda **kw: {"id": 999, "overridden": True},
            }
            skill_mod._registry = fake_registry

            result = route_action(mock_client, "create_partner", {"name": "Acme"})
            # Should use the builtin, not the auto-action
            assert result["id"] == 1  # from mock_client.create return value
            assert "overridden" not in result
        finally:
            skill_mod._registry = original

    def test_generic_crud_still_works_after_registry(self, mock_client):
        """Generic CRUD (search/create/update/delete) still dispatches correctly."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        original = skill_mod._registry

        try:
            fake_registry = MagicMock()
            fake_registry.get_auto_actions.return_value = {}
            skill_mod._registry = fake_registry

            result = route_action(mock_client, "search", {"model": "res.partner"})
            assert isinstance(result, list)
        finally:
            skill_mod._registry = original

    def test_no_registry_falls_through_to_generic(self, mock_client):
        """When registry is None, generic CRUD still works."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        original = skill_mod._registry

        try:
            skill_mod._registry = None
            result = route_action(mock_client, "search", {"model": "res.partner"})
            assert isinstance(result, list)
        finally:
            skill_mod._registry = original


# =============================================================
# Main stdin/stdout loop
# =============================================================

class TestMainLoop:
    @patch("openclaw_odoo.interfaces.openclaw_skill.load_config")
    @patch("openclaw_odoo.interfaces.openclaw_skill.OdooClient")
    def test_main_processes_json(self, MockClient, mock_load_config):
        from openclaw_odoo.interfaces.openclaw_skill import main

        mock_cfg = MagicMock()
        mock_load_config.return_value = mock_cfg
        client_instance = MagicMock()
        client_instance.search_read.return_value = []
        client_instance.fields_get.return_value = {}
        # Support context manager (main() now uses `with OdooClient(config) as client:`)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = client_instance

        input_data = json.dumps({"action": "search_orders", "params": {}})
        with patch("sys.stdin", StringIO(input_data)), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            main()
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert isinstance(parsed, (dict, list))


# =============================================================
# Gap 4: _get_registry lazy init test
# =============================================================

class TestGetRegistryLazyInit:
    def test_lazy_init_loads_registry(self, monkeypatch):
        """Test that _get_registry creates and loads a registry on first call."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        original = skill_mod._registry

        try:
            # Reset global to force lazy init path
            skill_mod._registry = None

            # Build mocks for the registry and auto_actions modules
            mock_registry_cls = MagicMock()
            mock_reg_instance = MagicMock()
            mock_reg_instance.all_models.return_value = [
                {"model": "x_test.model", "label": "Test Model"},
            ]
            mock_reg_instance.custom_models.return_value = [
                {"model": "x_test.model", "label": "Test Model"},
            ]
            mock_registry_cls.return_value = mock_reg_instance
            mock_reg_instance.get_auto_actions.return_value = {}

            mock_generate_crud = MagicMock(return_value={
                "search_x_test_models": lambda **kw: [],
            })
            mock_generate_wf = MagicMock(return_value={})

            # Patch the imports inside _get_registry
            monkeypatch.setattr(
                "openclaw_odoo.interfaces.openclaw_skill._registry", None
            )

            # We need to mock the lazy imports; use a fake module approach
            import types
            fake_registry_mod = types.ModuleType("openclaw_odoo.registry")
            fake_registry_mod.ModelRegistry = mock_registry_cls

            fake_auto_mod = types.ModuleType("openclaw_odoo.auto_actions")
            fake_auto_mod.generate_crud_actions = mock_generate_crud
            fake_auto_mod.generate_workflow_actions = mock_generate_wf

            import sys as _sys
            _sys.modules["openclaw_odoo.registry"] = fake_registry_mod
            _sys.modules["openclaw_odoo.auto_actions"] = fake_auto_mod

            mock_client = MagicMock()
            mock_client.config = MagicMock()

            result = skill_mod._get_registry(mock_client)

            # Verify the registry was loaded
            assert result is not None
            mock_reg_instance.load.assert_called_once()
            mock_reg_instance.register_auto_actions.assert_called_once()

        finally:
            skill_mod._registry = original
            # Clean up fake modules
            _sys.modules.pop("openclaw_odoo.registry", None)
            _sys.modules.pop("openclaw_odoo.auto_actions", None)

    def test_registry_init_failure_returns_none(self, monkeypatch):
        """When registry load() raises, _get_registry returns None."""
        import openclaw_odoo.interfaces.openclaw_skill as skill_mod
        original = skill_mod._registry

        try:
            skill_mod._registry = None

            mock_client = MagicMock()
            mock_client.config = MagicMock()

            # Make ModelRegistry.load() raise so init fails inside the try block
            from openclaw_odoo.registry import ModelRegistry
            original_init = ModelRegistry.__init__

            def _broken_init(self, config):
                raise RuntimeError("registry broken")

            monkeypatch.setattr(ModelRegistry, "__init__", _broken_init)

            result = skill_mod._get_registry(mock_client)
            assert result is None

        finally:
            skill_mod._registry = original
