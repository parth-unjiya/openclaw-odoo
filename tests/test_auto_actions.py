"""Tests for auto-generated CRUD, workflow, and analytics actions."""
import io
import logging
import pytest
from unittest.mock import MagicMock

from openclaw_odoo.auto_actions import (
    _pluralize,
    _action_names_for,
    generate_crud_actions,
    generate_workflow_actions,
    generate_auto_dashboard,
    generate_import_signatures,
)
from openclaw_odoo.errors import OdooRecordNotFoundError
from openclaw_odoo.registry import ModelInfo, FieldInfo, ModelRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fleet_info():
    return ModelInfo(
        name="x_fleet.vehicle",
        label="Fleet Vehicle",
        name_field="license_plate",
        fields={
            "name": FieldInfo(name="name", type="char", label="Name"),
            "license_plate": FieldInfo(name="license_plate", type="char", label="License Plate"),
            "driver_id": FieldInfo(name="driver_id", type="many2one", label="Driver", relation="hr.employee"),
        },
        access={"read": True, "write": True, "create": True, "unlink": False},
    )


# ---------------------------------------------------------------------------
# _pluralize
# ---------------------------------------------------------------------------

class TestPluralize:
    def test_regular_word(self):
        assert _pluralize("vehicle") == "vehicles"

    def test_word_ending_in_s(self):
        assert _pluralize("bus") == "buses"

    def test_word_ending_in_x(self):
        assert _pluralize("box") == "boxes"

    def test_word_ending_in_sh(self):
        assert _pluralize("dish") == "dishes"

    def test_word_ending_in_ch(self):
        assert _pluralize("batch") == "batches"

    def test_word_ending_in_consonant_y(self):
        assert _pluralize("category") == "categories"

    def test_word_ending_in_vowel_y(self):
        assert _pluralize("day") == "days"

    def test_single_char(self):
        # Edge case: single character word
        assert _pluralize("y") == "ys"  # len(word) > 1 guard


# ---------------------------------------------------------------------------
# _action_names_for
# ---------------------------------------------------------------------------

class TestActionNameGeneration:
    def test_generates_crud_names(self):
        names = _action_names_for("Fleet Vehicle")
        assert names["search"] == "search_fleet_vehicles"
        assert names["create"] == "create_fleet_vehicle"
        assert names["get"] == "get_fleet_vehicle"
        assert names["update"] == "update_fleet_vehicle"
        assert names["delete"] == "delete_fleet_vehicle"
        assert names["find"] == "find_fleet_vehicle"
        assert names["find_or_create"] == "find_or_create_fleet_vehicle"

    def test_single_word_label(self):
        names = _action_names_for("Vehicle")
        assert names["search"] == "search_vehicles"
        assert names["create"] == "create_vehicle"

    def test_multi_word_label(self):
        names = _action_names_for("Purchase Order Line")
        assert names["search"] == "search_purchase_order_lines"
        assert names["create"] == "create_purchase_order_line"

    def test_label_with_special_characters(self):
        names = _action_names_for("My Custom-Model (v2)")
        assert "search" in names
        # Should produce a valid snake_case slug
        assert names["create"].startswith("create_")

    def test_all_seven_operations_present(self):
        names = _action_names_for("Test Model")
        expected_ops = {"search", "create", "get", "update", "delete", "find", "find_or_create"}
        assert set(names.keys()) == expected_ops


# ---------------------------------------------------------------------------
# generate_crud_actions
# ---------------------------------------------------------------------------

class TestGenerateCrudActions:
    def test_generates_expected_actions(self, fleet_info):
        client = MagicMock()
        actions = generate_crud_actions(client, fleet_info)
        assert "search_fleet_vehicles" in actions
        assert "create_fleet_vehicle" in actions
        assert "get_fleet_vehicle" in actions
        assert "update_fleet_vehicle" in actions
        assert "delete_fleet_vehicle" in actions
        assert "find_fleet_vehicle" in actions
        assert "find_or_create_fleet_vehicle" in actions
        assert callable(actions["search_fleet_vehicles"])

    def test_search_action_calls_search_read(self, fleet_info):
        client = MagicMock()
        client.search_read.return_value = [{"id": 1, "name": "Truck"}]
        client.fields_get.return_value = {"name": {"type": "char", "string": "Name"}}
        actions = generate_crud_actions(client, fleet_info)
        result = actions["search_fleet_vehicles"](domain=[["name", "=", "Truck"]])
        client.search_read.assert_called_once()

    def test_search_with_explicit_fields(self, fleet_info):
        client = MagicMock()
        client.search_read.return_value = [{"id": 1, "name": "Truck"}]
        actions = generate_crud_actions(client, fleet_info)
        actions["search_fleet_vehicles"](fields=["name", "id"])
        # fields_get should NOT be called when fields are explicit
        client.fields_get.assert_not_called()

    def test_create_action(self, fleet_info):
        client = MagicMock()
        client.create.return_value = 42
        client.web_url.return_value = "http://localhost/odoo/x_fleet.vehicle/42"
        actions = generate_crud_actions(client, fleet_info)
        result = actions["create_fleet_vehicle"](values={"license_plate": "KA-01-1234"})
        assert result["id"] == 42
        assert result["web_url"] == "http://localhost/odoo/x_fleet.vehicle/42"

    def test_get_action(self, fleet_info):
        client = MagicMock()
        client.search_read.return_value = [{"id": 5, "license_plate": "KA-01-5678"}]
        actions = generate_crud_actions(client, fleet_info)
        result = actions["get_fleet_vehicle"](record_id=5)
        assert result["id"] == 5

    def test_get_action_not_found(self, fleet_info):
        client = MagicMock()
        client.search_read.return_value = []
        actions = generate_crud_actions(client, fleet_info)
        with pytest.raises(OdooRecordNotFoundError, match="Fleet Vehicle 999 not found"):
            actions["get_fleet_vehicle"](record_id=999)

    def test_update_action(self, fleet_info):
        client = MagicMock()
        client.web_url.return_value = "http://localhost/odoo/x_fleet.vehicle/5"
        actions = generate_crud_actions(client, fleet_info)
        result = actions["update_fleet_vehicle"](record_id=5, values={"license_plate": "NEW-001"})
        client.write.assert_called_once_with("x_fleet.vehicle", [5], {"license_plate": "NEW-001"})
        assert result["id"] == 5
        assert result["web_url"] == "http://localhost/odoo/x_fleet.vehicle/5"

    def test_delete_action_soft(self, fleet_info):
        client = MagicMock()
        actions = generate_crud_actions(client, fleet_info)
        result = actions["delete_fleet_vehicle"](record_id=5)
        client.write.assert_called_once_with("x_fleet.vehicle", [5], {"active": False})
        assert result["archived"] is True

    def test_delete_action_permanent(self, fleet_info):
        client = MagicMock()
        actions = generate_crud_actions(client, fleet_info)
        result = actions["delete_fleet_vehicle"](record_id=5, permanent=True)
        client.unlink.assert_called_once_with("x_fleet.vehicle", [5])
        assert result["deleted"] is True

    def test_find_action(self, fleet_info):
        client = MagicMock()
        client.search_read.return_value = [{"id": 1, "license_plate": "KA-01"}]
        actions = generate_crud_actions(client, fleet_info)
        result = actions["find_fleet_vehicle"](name="KA-01")
        client.search_read.assert_called_once_with(
            "x_fleet.vehicle", domain=[["license_plate", "ilike", "KA-01"]], limit=10
        )

    def test_find_or_create_finds_existing(self, fleet_info):
        client = MagicMock()
        # SmartActionHandler._fuzzy_find does exact match first
        client.search_read.return_value = [{"id": 7, "license_plate": "KA-01-1234"}]
        actions = generate_crud_actions(client, fleet_info)
        result = actions["find_or_create_fleet_vehicle"](name="KA-01-1234")
        assert result["id"] == 7
        assert result["created"] is False
        client.create.assert_not_called()

    def test_find_or_create_creates_new(self, fleet_info):
        client = MagicMock()
        # SmartActionHandler._fuzzy_find: exact returns [], ilike returns []
        client.search_read.return_value = []
        client.create.return_value = 99
        actions = generate_crud_actions(client, fleet_info)
        result = actions["find_or_create_fleet_vehicle"](name="NEW-001")
        assert result["id"] == 99
        assert result["created"] is True

    def test_find_or_create_with_extra_values(self, fleet_info):
        client = MagicMock()
        # SmartActionHandler._fuzzy_find: exact returns [], ilike returns []
        client.search_read.return_value = []
        client.create.return_value = 100
        actions = generate_crud_actions(client, fleet_info)
        result = actions["find_or_create_fleet_vehicle"](
            name="NEW-002", extra_values={"driver_id": 5}
        )
        client.create.assert_called_once_with(
            "x_fleet.vehicle", {"license_plate": "NEW-002", "driver_id": 5}
        )

    def test_skips_builtin_models(self):
        info = ModelInfo(name="res.partner", label="Contact", is_builtin=True)
        client = MagicMock()
        actions = generate_crud_actions(client, info)
        assert len(actions) == 0

    def test_generates_seven_actions(self, fleet_info):
        client = MagicMock()
        actions = generate_crud_actions(client, fleet_info)
        assert len(actions) == 7


# ---------------------------------------------------------------------------
# generate_workflow_actions
# ---------------------------------------------------------------------------

class TestGenerateWorkflowActions:
    def test_generates_workflow_actions(self, fleet_info):
        fleet_info.workflows = ["action_assign", "action_return"]
        client = MagicMock()
        actions = generate_workflow_actions(client, fleet_info)
        assert "assign_fleet_vehicle" in actions
        assert "return_fleet_vehicle" in actions

    def test_calls_execute_on_invoke(self, fleet_info):
        fleet_info.workflows = ["action_assign"]
        client = MagicMock()
        client.execute.return_value = True
        actions = generate_workflow_actions(client, fleet_info)
        actions["assign_fleet_vehicle"](record_id=12)
        client.execute.assert_called_once_with("x_fleet.vehicle", "action_assign", [12])

    def test_strips_button_prefix(self, fleet_info):
        fleet_info.workflows = ["button_validate"]
        client = MagicMock()
        actions = generate_workflow_actions(client, fleet_info)
        assert "validate_fleet_vehicle" in actions

    def test_skips_builtin_models(self):
        info = ModelInfo(name="sale.order", label="Sales Order", is_builtin=True,
                         workflows=["action_confirm"])
        client = MagicMock()
        actions = generate_workflow_actions(client, info)
        assert len(actions) == 0

    def test_skips_models_without_workflows(self, fleet_info):
        fleet_info.workflows = []
        client = MagicMock()
        actions = generate_workflow_actions(client, fleet_info)
        assert len(actions) == 0

    def test_skips_unsafe_method_names(self, fleet_info):
        """Workflow methods not matching safe prefixes/set are skipped."""
        fleet_info.workflows = [
            "action_assign",       # safe prefix
            "button_validate",     # safe prefix
            "confirm",             # safe set
            "write",               # UNSAFE -- should be skipped
            "_private_method",     # UNSAFE -- should be skipped
            "unlink",              # UNSAFE -- should be skipped
        ]
        client = MagicMock()
        actions = generate_workflow_actions(client, fleet_info)
        # Only the 3 safe methods should produce actions
        assert len(actions) == 3
        action_names = list(actions.keys())
        assert "assign_fleet_vehicle" in action_names
        assert "validate_fleet_vehicle" in action_names
        assert "confirm_fleet_vehicle" in action_names

    def test_logs_warning_for_unsafe_methods(self, fleet_info):
        """Unsafe workflow methods should trigger a warning log."""
        fleet_info.workflows = ["write"]
        client = MagicMock()
        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        log_handler.setLevel(logging.WARNING)
        log = logging.getLogger("openclaw_odoo.auto_actions")
        log.addHandler(log_handler)
        try:
            actions = generate_workflow_actions(client, fleet_info)
            assert len(actions) == 0
            log_output = log_stream.getvalue()
            assert "write" in log_output
            assert "Skipping" in log_output
        finally:
            log.removeHandler(log_handler)

    def test_multiple_workflows_independent_closures(self, fleet_info):
        fleet_info.workflows = ["action_assign", "action_return"]
        client = MagicMock()
        client.execute.return_value = True
        actions = generate_workflow_actions(client, fleet_info)

        # Call assign
        actions["assign_fleet_vehicle"](record_id=1)
        client.execute.assert_called_with("x_fleet.vehicle", "action_assign", [1])

        # Call return
        actions["return_fleet_vehicle"](record_id=2)
        client.execute.assert_called_with("x_fleet.vehicle", "action_return", [2])


# ---------------------------------------------------------------------------
# generate_auto_dashboard
# ---------------------------------------------------------------------------

class TestGenerateAutoDashboard:
    def test_generates_dashboard_with_money_and_status(self, fleet_info):
        """Dashboard uses read_group for both money aggregation and status grouping."""
        fleet_info.money_fields = ["fuel_cost"]
        fleet_info.status_field = "x_status"
        client = MagicMock()

        def _execute_side_effect(model, method, *args, **kwargs):
            if method == "read_group":
                groupby_arg = args[2] if len(args) > 2 else []
                if groupby_arg == []:
                    return [{"fuel_cost": 1000}]
                elif groupby_arg == ["x_status"]:
                    return [
                        {"x_status": "available", "x_status_count": 2},
                        {"x_status": "in_use", "x_status_count": 1},
                    ]
            return None

        client.execute.side_effect = _execute_side_effect
        client.search_count.return_value = 3
        client.search_read.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

        result = generate_auto_dashboard(client, fleet_info)
        assert result["total_records"] == 3
        assert result["totals"]["fuel_cost"] == 1000
        assert result["by_status"]["available"] == 2
        assert result["by_status"]["in_use"] == 1

    def test_handles_model_without_money_or_status(self):
        info = ModelInfo(name="x_simple.model", label="Simple")
        client = MagicMock()
        client.search_count.return_value = 5
        client.search_read.return_value = [{"id": i} for i in range(5)]

        result = generate_auto_dashboard(client, info)
        assert result["total_records"] == 5
        assert result["totals"] == {}
        assert result["by_status"] == {}
        # execute (read_group) should NOT be called when no money/status fields
        client.execute.assert_not_called()

    def test_dashboard_includes_model_metadata(self, fleet_info):
        fleet_info.money_fields = []
        fleet_info.status_field = None
        client = MagicMock()
        client.search_count.return_value = 10
        client.search_read.return_value = []

        result = generate_auto_dashboard(client, fleet_info)
        assert result["model"] == "x_fleet.vehicle"
        assert result["label"] == "Fleet Vehicle"

    def test_dashboard_with_date_filters(self):
        info = ModelInfo(
            name="x_custom.order",
            label="Custom Order",
            date_fields=["order_date"],
            money_fields=["amount"],
            status_field=None,
        )
        client = MagicMock()
        client.search_count.return_value = 2
        client.execute.return_value = [{"amount": 300}]
        client.search_read.return_value = [
            {"id": 1, "amount": 100},
            {"id": 2, "amount": 200},
        ]

        result = generate_auto_dashboard(client, info, date_from="2026-01-01", date_to="2026-12-31")
        assert result["total_records"] == 2
        assert result["totals"]["amount"] == 300
        # Verify domain was built with date filters
        count_call_args = client.search_count.call_args
        domain = count_call_args[0][1] if len(count_call_args[0]) > 1 else count_call_args[1].get("domain", [])
        assert any("order_date" in str(d) for d in domain)

    def test_dashboard_recent_records(self, fleet_info):
        fleet_info.money_fields = []
        fleet_info.status_field = None
        client = MagicMock()
        client.search_count.return_value = 100
        recent_data = [{"id": i, "name": f"Record {i}"} for i in range(10)]
        client.search_read.return_value = recent_data

        result = generate_auto_dashboard(client, fleet_info)
        assert result["recent"] == recent_data

    def test_dashboard_status_via_read_group(self):
        """Status grouping uses read_group instead of fetching all records."""
        info = ModelInfo(
            name="x_custom.model",
            label="Custom",
            status_field="state",
            money_fields=[],
        )
        client = MagicMock()
        client.search_count.return_value = 2
        client.execute.return_value = [
            {"state": "draft", "state_count": 1},
            {"state": "done", "state_count": 1},
        ]
        client.search_read.return_value = [{"id": 1}, {"id": 2}]

        result = generate_auto_dashboard(client, info)
        assert result["by_status"]["draft"] == 1
        assert result["by_status"]["done"] == 1
        client.execute.assert_called_once_with(
            "x_custom.model", "read_group",
            [], ["state"], ["state"],
        )

    def test_dashboard_handles_none_money_values(self):
        """read_group returns None for a money field -- treated as 0."""
        info = ModelInfo(
            name="x_test.model",
            label="Test",
            money_fields=["amount"],
            status_field=None,
        )
        client = MagicMock()
        client.search_count.return_value = 2
        client.execute.return_value = [{"amount": None}]
        client.search_read.return_value = [{"id": 1}, {"id": 2}]

        result = generate_auto_dashboard(client, info)
        assert result["totals"]["amount"] == 0

    def test_dashboard_money_read_group_empty(self):
        """read_group returns empty list -- totals should stay empty."""
        info = ModelInfo(
            name="x_test.model",
            label="Test",
            money_fields=["amount"],
            status_field=None,
        )
        client = MagicMock()
        client.search_count.return_value = 0
        client.execute.return_value = []
        client.search_read.return_value = []

        result = generate_auto_dashboard(client, info)
        assert result["totals"] == {}

    def test_dashboard_uses_read_group_not_search_read_for_aggregation(self, fleet_info):
        """search_read is NOT called with limit=None (the old OOM pattern)."""
        fleet_info.money_fields = ["fuel_cost"]
        fleet_info.status_field = "x_status"
        client = MagicMock()
        client.search_count.return_value = 1000

        def _execute_side_effect(model, method, *args, **kwargs):
            if method == "read_group":
                groupby_arg = args[2] if len(args) > 2 else []
                if groupby_arg == []:
                    return [{"fuel_cost": 50000}]
                elif groupby_arg == ["x_status"]:
                    return [{"x_status": "active", "x_status_count": 1000}]
            return None

        client.execute.side_effect = _execute_side_effect
        client.search_read.return_value = [{"id": i} for i in range(10)]

        generate_auto_dashboard(client, fleet_info)
        # search_read should only be called once (for recent records, limit=10)
        assert client.search_read.call_count == 1
        call_kwargs = client.search_read.call_args[1]
        assert call_kwargs.get("limit") == 10


# ---------------------------------------------------------------------------
# generate_import_signatures
# ---------------------------------------------------------------------------

class TestGenerateImportSignatures:
    def test_generates_signatures_for_custom_models(self):
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        # Manually insert a model
        registry._models["x_fleet.vehicle"] = ModelInfo(
            name="x_fleet.vehicle",
            label="Fleet Vehicle",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "plate": FieldInfo(name="plate", type="char", label="License Plate", store=True),
                "driver_id": FieldInfo(name="driver_id", type="many2one", label="Driver", store=True),
                "fuel_cost": FieldInfo(name="fuel_cost", type="monetary", label="Fuel Cost", store=True),
            },
        )

        sigs = generate_import_signatures(registry)
        assert len(sigs) == 1
        model_name = list(sigs.values())[0]
        assert model_name == "x_fleet.vehicle"

    def test_skips_builtin_models(self):
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["res.partner"] = ModelInfo(
            name="res.partner",
            label="Contact",
            is_builtin=True,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "email": FieldInfo(name="email", type="char", label="Email", store=True),
                "phone": FieldInfo(name="phone", type="char", label="Phone", store=True),
            },
        )

        sigs = generate_import_signatures(registry)
        assert len(sigs) == 0

    def test_skips_models_with_fewer_than_three_fields(self):
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["x_tiny.model"] = ModelInfo(
            name="x_tiny.model",
            label="Tiny",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "active": FieldInfo(name="active", type="boolean", label="Active", store=True),
            },
        )

        sigs = generate_import_signatures(registry)
        assert len(sigs) == 0

    def test_signature_keys_are_lowercase_labels(self):
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["x_test.model"] = ModelInfo(
            name="x_test.model",
            label="Test Model",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "code": FieldInfo(name="code", type="char", label="Code", store=True),
                "amount": FieldInfo(name="amount", type="float", label="Amount", store=True),
                "ref": FieldInfo(name="ref", type="char", label="Reference", store=True),
            },
        )

        sigs = generate_import_signatures(registry)
        key = list(sigs.keys())[0]
        assert isinstance(key, frozenset)
        assert "name" in key
        assert "code" in key
        assert "amount" in key
        assert "reference" in key

    def test_excludes_non_importable_field_types(self):
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["x_test.model"] = ModelInfo(
            name="x_test.model",
            label="Test Model",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "code": FieldInfo(name="code", type="char", label="Code", store=True),
                "notes": FieldInfo(name="notes", type="text", label="Notes", store=True),
                "image": FieldInfo(name="image", type="binary", label="Image", store=True),
                "tags": FieldInfo(name="tags", type="many2many", label="Tags", store=True),
                "amount": FieldInfo(name="amount", type="float", label="Amount", store=True),
            },
        )

        sigs = generate_import_signatures(registry)
        key = list(sigs.keys())[0]
        # binary and many2many should be excluded; text IS included
        assert "image" not in key
        assert "tags" not in key
        assert "notes" in key
