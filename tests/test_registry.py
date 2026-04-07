"""Tests for ModelRegistry, ModelInfo, and FieldInfo."""
import json
import logging
import pytest
from unittest.mock import MagicMock, patch

from openclaw_odoo.registry import (
    ModelInfo, FieldInfo, ModelRegistry, _BUILTIN_MODELS, _MONEY_PATTERNS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_cache():
    """A minimal discovery cache with one custom model."""
    return {
        "version": "1.0",
        "odoo_url": "http://localhost:8069",
        "database": "testdb",
        "models": {
            "x_fleet.vehicle": {
                "label": "Fleet Vehicle",
                "module": "x_fleet",
                "description": "Fleet vehicles",
                "access": {"read": True, "write": True, "create": True, "unlink": False},
                "fields": {
                    "name": {"type": "char", "string": "Name", "required": True, "store": True},
                    "license_plate": {"type": "char", "string": "License Plate", "store": True},
                    "fuel_cost": {"type": "monetary", "string": "Fuel Cost", "store": True},
                    "daily_rate": {"type": "float", "string": "Daily Rate", "store": True},
                    "mileage_price": {"type": "float", "string": "Mileage Price", "store": True},
                    "x_status": {
                        "type": "selection", "string": "Status",
                        "selection": [["available", "Available"], ["in_use", "In Use"]],
                        "store": True,
                    },
                    "next_service_date": {"type": "date", "string": "Next Service", "store": True},
                    "last_inspection": {"type": "datetime", "string": "Last Inspection", "store": True},
                    "driver_id": {
                        "type": "many2one", "string": "Driver",
                        "relation": "hr.employee", "store": True,
                    },
                },
                "workflows": ["action_assign"],
            },
        },
    }


@pytest.fixture
def config_mock():
    """A mock config with matching URL/DB and no hints."""
    config = MagicMock()
    config.model_hints = {}
    config.odoo_url = "http://localhost:8069"
    config.odoo_db = "testdb"
    return config


def _write_cache(tmp_path, cache_data):
    """Helper: write cache JSON to a temp file and return path string."""
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(cache_data))
    return str(cache_path)


def _make_registry(config, cache_path):
    """Helper: create a registry and load from cache file."""
    registry = ModelRegistry(config)
    registry.load(cache_path)
    return registry


# ---------------------------------------------------------------------------
# DataClass tests
# ---------------------------------------------------------------------------

class TestFieldInfo:
    def test_create_field_info(self):
        fi = FieldInfo(name="amount", type="monetary", label="Amount")
        assert fi.name == "amount"
        assert fi.type == "monetary"
        assert fi.label == "Amount"
        assert fi.required is False
        assert fi.readonly is False
        assert fi.relation is None
        assert fi.selection is None
        assert fi.store is True

    def test_field_info_with_relation(self):
        fi = FieldInfo(
            name="partner_id", type="many2one", label="Partner",
            relation="res.partner", required=True,
        )
        assert fi.relation == "res.partner"
        assert fi.required is True

    def test_field_info_with_selection(self):
        fi = FieldInfo(
            name="state", type="selection", label="State",
            selection=[["draft", "Draft"], ["done", "Done"]],
        )
        assert len(fi.selection) == 2


class TestModelInfo:
    def test_create_model_info(self):
        info = ModelInfo(
            name="x_fleet.vehicle",
            label="Fleet Vehicle",
            description="Fleet management",
            module="x_fleet",
            name_field="license_plate",
            aliases=["vehicle", "fleet"],
            fields={},
            important_fields=["driver_id"],
            money_fields=["fuel_cost"],
            date_fields=["next_service_date"],
            status_field="x_status",
            workflows=["action_assign"],
            access={"read": True, "write": True, "create": True, "unlink": False},
            analytics_config={"group_by": "x_status", "sum_fields": ["fuel_cost"]},
            is_builtin=False,
        )
        assert info.name == "x_fleet.vehicle"
        assert info.label == "Fleet Vehicle"
        assert not info.is_builtin
        assert info.name_field == "license_plate"
        assert "vehicle" in info.aliases
        assert "fuel_cost" in info.money_fields

    def test_defaults(self):
        info = ModelInfo(name="x_test", label="Test")
        assert info.description == ""
        assert info.module == ""
        assert info.name_field == "name"
        assert info.aliases == []
        assert info.fields == {}
        assert info.money_fields == []
        assert info.date_fields == []
        assert info.status_field is None
        assert info.workflows == []
        assert info.access == {}
        assert info.analytics_config is None
        assert info.is_builtin is False


# ---------------------------------------------------------------------------
# _BUILTIN_MODELS
# ---------------------------------------------------------------------------

class TestBuiltinModels:
    def test_contains_all_19_models(self):
        assert len(_BUILTIN_MODELS) == 19

    def test_known_builtins_present(self):
        expected = {
            "res.partner", "sale.order", "crm.lead", "product.product",
            "account.move", "hr.employee", "project.task", "project.project",
            "purchase.order", "calendar.event", "stock.quant",
            "sale.order.line", "purchase.order.line", "account.move.line",
            "helpdesk.ticket", "hr.attendance", "hr.leave", "hr.expense",
            "account.analytic.line",
        }
        assert _BUILTIN_MODELS == expected

    def test_is_frozenset(self):
        assert isinstance(_BUILTIN_MODELS, frozenset)


# ---------------------------------------------------------------------------
# _MONEY_PATTERNS
# ---------------------------------------------------------------------------

class TestMoneyPatterns:
    @pytest.mark.parametrize("name", [
        "cost", "fuel_cost", "unit_price", "total_amount",
        "monthly_revenue", "service_fee", "late_charge",
        "base_salary", "hourly_wage",
    ])
    def test_matches_money_names(self, name):
        assert _MONEY_PATTERNS.search(name) is not None

    @pytest.mark.parametrize("name", [
        "name", "driver_id", "status", "create_date", "color",
    ])
    def test_does_not_match_non_money(self, name):
        assert _MONEY_PATTERNS.search(name) is None


# ---------------------------------------------------------------------------
# ModelRegistry -- load
# ---------------------------------------------------------------------------

class TestRegistryLoad:
    def test_load_from_cache(self, sample_cache, config_mock, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)
        registry = _make_registry(config_mock, cache_path)

        info = registry.get("x_fleet.vehicle")
        assert info is not None
        assert info.label == "Fleet Vehicle"
        assert "fuel_cost" in info.money_fields  # auto-inferred (monetary)
        assert "mileage_price" in info.money_fields  # auto-inferred (float + price pattern)
        assert "next_service_date" in info.date_fields  # auto-inferred
        assert "last_inspection" in info.date_fields  # auto-inferred
        assert info.status_field == "x_status"  # auto-inferred

    def test_user_hints_override_auto_inference(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {
            "x_fleet.vehicle": {
                "name_field": "license_plate",
                "aliases": ["fleet", "car"],
                "money_fields": ["fuel_cost"],
                "analytics": {"group_by": "x_status", "sum_fields": ["fuel_cost"]},
            }
        }
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"

        registry = _make_registry(config, cache_path)

        info = registry.get("x_fleet.vehicle")
        assert info.name_field == "license_plate"  # from hint
        assert info.money_fields == ["fuel_cost"]  # hint overrides auto-inference
        assert info.analytics_config == {"group_by": "x_status", "sum_fields": ["fuel_cost"]}

    def test_find_by_alias(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {
            "x_fleet.vehicle": {"aliases": ["fleet", "car"]}
        }
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"

        registry = _make_registry(config, cache_path)

        assert registry.find("fleet") is not None
        assert registry.find("fleet").name == "x_fleet.vehicle"
        assert registry.find("car").name == "x_fleet.vehicle"
        assert registry.find("nonexistent") is None

    def test_stale_cache_returns_empty(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {}
        config.odoo_url = "http://localhost:9999"  # different URL = stale
        config.odoo_db = "testdb"

        registry = _make_registry(config, cache_path)
        assert len(registry.all_models()) == 0

    def test_stale_db_returns_empty(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {}
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "different_db"  # different DB = stale

        registry = _make_registry(config, cache_path)
        assert len(registry.all_models()) == 0

    def test_missing_cache_returns_empty(self, tmp_path):
        config = MagicMock()
        config.model_hints = {}

        registry = ModelRegistry(config)
        registry.load(str(tmp_path / "nonexistent.json"))
        assert len(registry.all_models()) == 0

    def test_builtin_models_flagged(self, sample_cache, config_mock, tmp_path):
        # Add a builtin model to the cache
        sample_cache["models"]["res.partner"] = {
            "label": "Contact", "module": "base", "description": "",
            "access": {"read": True}, "fields": {}, "workflows": [],
        }
        cache_path = _write_cache(tmp_path, sample_cache)

        registry = _make_registry(config_mock, cache_path)

        assert registry.get("res.partner").is_builtin is True
        assert registry.get("x_fleet.vehicle").is_builtin is False

    def test_load_clears_previous_data(self, sample_cache, config_mock, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        registry = _make_registry(config_mock, cache_path)
        assert len(registry.all_models()) == 1

        # Load again with nonexistent cache (returns empty)
        registry.load(str(tmp_path / "nonexistent.json"))
        assert len(registry.all_models()) == 0


# ---------------------------------------------------------------------------
# ModelRegistry -- find / resolve / get
# ---------------------------------------------------------------------------

class TestRegistryLookups:
    @pytest.fixture
    def loaded_registry(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)
        config = MagicMock()
        config.model_hints = {"x_fleet.vehicle": {"aliases": ["fleet", "car"]}}
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"
        return _make_registry(config, cache_path)

    def test_get_exact_name(self, loaded_registry):
        assert loaded_registry.get("x_fleet.vehicle") is not None
        assert loaded_registry.get("x_fleet.vehicle").name == "x_fleet.vehicle"

    def test_get_returns_none_for_missing(self, loaded_registry):
        assert loaded_registry.get("nonexistent") is None

    def test_find_by_exact_name(self, loaded_registry):
        assert loaded_registry.find("x_fleet.vehicle").name == "x_fleet.vehicle"

    def test_find_by_alias(self, loaded_registry):
        assert loaded_registry.find("fleet").name == "x_fleet.vehicle"
        assert loaded_registry.find("car").name == "x_fleet.vehicle"

    def test_find_by_label_substring(self, loaded_registry):
        assert loaded_registry.find("Fleet").name == "x_fleet.vehicle"
        assert loaded_registry.find("Vehicle").name == "x_fleet.vehicle"

    def test_find_returns_none_for_no_match(self, loaded_registry):
        assert loaded_registry.find("zzz_nothing") is None

    def test_resolve_returns_model(self, loaded_registry):
        info = loaded_registry.resolve("fleet")
        assert info.name == "x_fleet.vehicle"

    def test_resolve_raises_for_missing(self, loaded_registry):
        from openclaw_odoo.errors import OdooClawError
        with pytest.raises(OdooClawError, match="Model not found"):
            loaded_registry.resolve("nonexistent_xyz")

    def test_find_auto_alias_from_label(self, sample_cache, config_mock, tmp_path):
        """Non-builtin models get an auto-alias from their label."""
        cache_path = _write_cache(tmp_path, sample_cache)
        registry = _make_registry(config_mock, cache_path)

        # "Fleet Vehicle" -> auto alias "fleet_vehicle"
        assert registry.find("fleet_vehicle") is not None
        assert registry.find("fleet_vehicle").name == "x_fleet.vehicle"


# ---------------------------------------------------------------------------
# ModelRegistry -- query methods
# ---------------------------------------------------------------------------

class TestRegistryQueries:
    @pytest.fixture
    def multi_model_cache(self):
        return {
            "version": "1.0",
            "odoo_url": "http://localhost:8069",
            "database": "testdb",
            "models": {
                "res.partner": {
                    "label": "Contact", "module": "base", "description": "",
                    "access": {"read": True}, "fields": {}, "workflows": [],
                },
                "x_fleet.vehicle": {
                    "label": "Fleet Vehicle", "module": "x_fleet",
                    "description": "Fleet",
                    "access": {"read": True, "write": True},
                    "fields": {
                        "fuel_cost": {"type": "monetary", "string": "Fuel Cost", "store": True},
                        "next_service_date": {"type": "date", "string": "Next Service", "store": True},
                    },
                    "workflows": ["action_assign"],
                },
                "x_simple.model": {
                    "label": "Simple Model", "module": "x_simple",
                    "description": "",
                    "access": {"read": True},
                    "fields": {
                        "name": {"type": "char", "string": "Name", "store": True},
                    },
                    "workflows": [],
                },
            },
        }

    @pytest.fixture
    def multi_registry(self, multi_model_cache, config_mock, tmp_path):
        cache_path = _write_cache(tmp_path, multi_model_cache)
        return _make_registry(config_mock, cache_path)

    def test_all_models(self, multi_registry):
        all_m = multi_registry.all_models()
        assert len(all_m) == 3
        names = {m.name for m in all_m}
        assert "res.partner" in names
        assert "x_fleet.vehicle" in names
        assert "x_simple.model" in names

    def test_custom_models(self, multi_registry):
        custom = multi_registry.custom_models()
        names = {m.name for m in custom}
        assert "x_fleet.vehicle" in names
        assert "x_simple.model" in names
        assert "res.partner" not in names  # builtin excluded

    def test_models_with_analytics(self, multi_registry):
        analytics = multi_registry.models_with_analytics()
        names = {m.name for m in analytics}
        assert "x_fleet.vehicle" in names  # has money + date fields
        assert "x_simple.model" not in names  # no money/date
        # res.partner has no fields in this cache, so no analytics
        assert "res.partner" not in names

    def test_models_with_workflows(self, multi_registry):
        wf = multi_registry.models_with_workflows()
        names = {m.name for m in wf}
        assert "x_fleet.vehicle" in names  # has action_assign
        assert "x_simple.model" not in names  # no workflows
        assert "res.partner" not in names


# ---------------------------------------------------------------------------
# Auto-actions registration
# ---------------------------------------------------------------------------

class TestAutoActions:
    def test_register_and_get_auto_actions(self, config_mock):
        registry = ModelRegistry(config_mock)
        assert registry.get_auto_actions() == {}

        def handler_a():
            pass
        def handler_b():
            pass

        registry.register_auto_actions({
            "search_fleet_vehicles": handler_a,
            "create_fleet_vehicle": handler_b,
        })

        actions = registry.get_auto_actions()
        assert "search_fleet_vehicles" in actions
        assert "create_fleet_vehicle" in actions
        assert actions["search_fleet_vehicles"] is handler_a

    def test_register_merges_not_replaces(self, config_mock):
        registry = ModelRegistry(config_mock)

        registry.register_auto_actions({"action_a": lambda: 1})
        registry.register_auto_actions({"action_b": lambda: 2})

        actions = registry.get_auto_actions()
        assert "action_a" in actions
        assert "action_b" in actions

    def test_get_returns_copy(self, config_mock):
        registry = ModelRegistry(config_mock)
        registry.register_auto_actions({"action_a": lambda: 1})

        actions = registry.get_auto_actions()
        actions["action_a"] = "modified"

        # Original is unmodified
        assert callable(registry.get_auto_actions()["action_a"])


# ---------------------------------------------------------------------------
# Auto-inference (_infer_* static methods)
# ---------------------------------------------------------------------------

class TestInferMoneyFields:
    def test_monetary_type(self):
        fields = {
            "amount": FieldInfo(name="amount", type="monetary", label="Amount"),
        }
        result = ModelRegistry._infer_money_fields(fields)
        assert result == ["amount"]

    def test_float_with_money_pattern(self):
        fields = {
            "fuel_cost": FieldInfo(name="fuel_cost", type="float", label="Fuel Cost"),
            "unit_price": FieldInfo(name="unit_price", type="float", label="Unit Price"),
            "total_amount": FieldInfo(name="total_amount", type="float", label="Total Amount"),
        }
        result = ModelRegistry._infer_money_fields(fields)
        assert "fuel_cost" in result
        assert "unit_price" in result
        assert "total_amount" in result

    def test_float_without_money_pattern_excluded(self):
        fields = {
            "quantity": FieldInfo(name="quantity", type="float", label="Quantity"),
            "weight": FieldInfo(name="weight", type="float", label="Weight"),
        }
        result = ModelRegistry._infer_money_fields(fields)
        assert result == []

    def test_non_float_non_monetary_excluded(self):
        fields = {
            "price_label": FieldInfo(name="price_label", type="char", label="Price Label"),
            "cost_center_id": FieldInfo(name="cost_center_id", type="many2one", label="Cost Center"),
        }
        result = ModelRegistry._infer_money_fields(fields)
        assert result == []

    def test_empty_fields(self):
        assert ModelRegistry._infer_money_fields({}) == []


class TestInferDateFields:
    def test_date_fields(self):
        fields = {
            "start_date": FieldInfo(name="start_date", type="date", label="Start", store=True),
            "end_date": FieldInfo(name="end_date", type="datetime", label="End", store=True),
        }
        result = ModelRegistry._infer_date_fields(fields)
        assert "start_date" in result
        assert "end_date" in result

    def test_computed_dates_excluded(self):
        fields = {
            "computed_date": FieldInfo(name="computed_date", type="date", label="Computed", store=False),
        }
        result = ModelRegistry._infer_date_fields(fields)
        assert result == []

    def test_non_date_excluded(self):
        fields = {
            "name": FieldInfo(name="name", type="char", label="Name"),
        }
        result = ModelRegistry._infer_date_fields(fields)
        assert result == []

    def test_empty_fields(self):
        assert ModelRegistry._infer_date_fields({}) == []


class TestInferStatusField:
    def test_state_selection(self):
        fields = {
            "state": FieldInfo(
                name="state", type="selection", label="State",
                selection=[["draft", "Draft"], ["done", "Done"]],
            ),
        }
        result = ModelRegistry._infer_status_field(fields)
        assert result == "state"

    def test_x_status_selection(self):
        fields = {
            "x_status": FieldInfo(
                name="x_status", type="selection", label="Status",
                selection=[["active", "Active"]],
            ),
        }
        result = ModelRegistry._infer_status_field(fields)
        assert result == "x_status"

    def test_priority_order(self):
        """state has priority over status, x_status, etc."""
        fields = {
            "x_status": FieldInfo(name="x_status", type="selection", label="X Status",
                                  selection=[["a", "A"]]),
            "state": FieldInfo(name="state", type="selection", label="State",
                               selection=[["draft", "Draft"]]),
            "status": FieldInfo(name="status", type="selection", label="Status",
                                selection=[["open", "Open"]]),
        }
        result = ModelRegistry._infer_status_field(fields)
        assert result == "state"

    def test_non_selection_state_ignored(self):
        fields = {
            "state": FieldInfo(name="state", type="char", label="State"),
        }
        result = ModelRegistry._infer_status_field(fields)
        assert result is None

    def test_no_status_field(self):
        fields = {
            "name": FieldInfo(name="name", type="char", label="Name"),
        }
        result = ModelRegistry._infer_status_field(fields)
        assert result is None

    def test_empty_fields(self):
        assert ModelRegistry._infer_status_field({}) is None


class TestInferNameField:
    def test_first_required_char(self):
        fields = {
            "code": FieldInfo(name="code", type="char", label="Code", required=True),
            "name": FieldInfo(name="name", type="char", label="Name", required=True),
        }
        result = ModelRegistry._infer_name_field(fields)
        assert result == "code"  # first in dict iteration

    def test_fallback_to_name(self):
        fields = {
            "amount": FieldInfo(name="amount", type="float", label="Amount"),
        }
        result = ModelRegistry._infer_name_field(fields)
        assert result == "name"

    def test_ignores_non_required(self):
        fields = {
            "description": FieldInfo(name="description", type="char", label="Desc", required=False),
        }
        result = ModelRegistry._infer_name_field(fields)
        assert result == "name"

    def test_empty_fields(self):
        assert ModelRegistry._infer_name_field({}) == "name"


# ---------------------------------------------------------------------------
# Alias collision warning
# ---------------------------------------------------------------------------

class TestAliasCollision:
    def test_collision_logs_warning(self, sample_cache, tmp_path, caplog):
        """When two models claim the same alias, a warning is logged."""
        # Add a second custom model with a conflicting alias
        sample_cache["models"]["x_rental.vehicle"] = {
            "label": "Rental Vehicle", "module": "x_rental",
            "description": "",
            "access": {"read": True},
            "fields": {},
            "workflows": [],
        }
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {
            "x_fleet.vehicle": {"aliases": ["vehicle"]},
            "x_rental.vehicle": {"aliases": ["vehicle"]},  # collision!
        }
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"

        registry = ModelRegistry(config)
        with caplog.at_level(logging.WARNING, logger="openclaw_odoo.registry"):
            registry.load(cache_path)

        assert any("Alias collision" in msg for msg in caplog.messages)

    def test_auto_alias_no_collision_with_user_alias(self, sample_cache, tmp_path):
        """Auto-inferred label alias yields to user-defined aliases."""
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {
            "x_fleet.vehicle": {"aliases": ["fleet_vehicle"]},
        }
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"

        registry = _make_registry(config, cache_path)

        # User alias takes precedence, auto-alias from label is also "fleet_vehicle"
        # but since user registered first, auto-alias is skipped (no collision warning)
        assert registry.find("fleet_vehicle").name == "x_fleet.vehicle"


# ---------------------------------------------------------------------------
# discover() delegates to full_discovery then load
# ---------------------------------------------------------------------------

class TestRegistryDiscover:
    def test_discover_calls_full_discovery_and_load(self, config_mock, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        client = MagicMock()

        registry = ModelRegistry(config_mock)

        with patch("openclaw_odoo.discovery.full_discovery") as mock_fd:
            mock_fd.return_value = {}
            registry.discover(client, cache_path=cache_path)
            mock_fd.assert_called_once_with(client, cache_path=cache_path)


# ---------------------------------------------------------------------------
# _build_fields
# ---------------------------------------------------------------------------

class TestBuildFields:
    def test_builds_field_info_objects(self, config_mock):
        registry = ModelRegistry(config_mock)
        raw = {
            "name": {"type": "char", "string": "Name", "required": True, "store": True},
            "partner_id": {
                "type": "many2one", "string": "Partner",
                "relation": "res.partner", "store": True,
            },
        }
        fields = registry._build_fields(raw)
        assert isinstance(fields["name"], FieldInfo)
        assert fields["name"].type == "char"
        assert fields["name"].required is True
        assert fields["partner_id"].relation == "res.partner"

    def test_defaults_for_missing_keys(self, config_mock):
        registry = ModelRegistry(config_mock)
        raw = {"x_field": {"type": "char"}}
        fields = registry._build_fields(raw)
        fi = fields["x_field"]
        assert fi.label == "x_field"  # defaults to field name
        assert fi.required is False
        assert fi.readonly is False
        assert fi.relation is None
        assert fi.selection is None
        assert fi.store is True

    def test_empty_raw(self, config_mock):
        registry = ModelRegistry(config_mock)
        assert registry._build_fields({}) == {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_model_with_no_fields(self, config_mock, tmp_path):
        cache = {
            "version": "1.0",
            "odoo_url": "http://localhost:8069",
            "database": "testdb",
            "models": {
                "x_empty.model": {
                    "label": "Empty", "module": "x_empty",
                    "description": "", "access": {}, "fields": {},
                    "workflows": [],
                },
            },
        }
        cache_path = _write_cache(tmp_path, cache)
        registry = _make_registry(config_mock, cache_path)

        info = registry.get("x_empty.model")
        assert info is not None
        assert info.money_fields == []
        assert info.date_fields == []
        assert info.status_field is None
        assert info.name_field == "name"  # default fallback

    def test_cache_with_empty_models_dict(self, config_mock, tmp_path):
        cache = {
            "version": "1.0",
            "odoo_url": "http://localhost:8069",
            "database": "testdb",
            "models": {},
        }
        cache_path = _write_cache(tmp_path, cache)
        registry = _make_registry(config_mock, cache_path)
        assert registry.all_models() == []

    def test_find_case_insensitive_alias(self, sample_cache, tmp_path):
        cache_path = _write_cache(tmp_path, sample_cache)

        config = MagicMock()
        config.model_hints = {
            "x_fleet.vehicle": {"aliases": ["Fleet", "CAR"]},
        }
        config.odoo_url = "http://localhost:8069"
        config.odoo_db = "testdb"

        registry = _make_registry(config, cache_path)

        # Aliases are stored lowercase; find() checks lowercase too
        assert registry.find("fleet").name == "x_fleet.vehicle"
        assert registry.find("car").name == "x_fleet.vehicle"
        assert registry.find("FLEET") is not None  # label substring match

    def test_fields_have_correct_types(self, sample_cache, config_mock, tmp_path):
        """All fields from cache are converted to FieldInfo objects."""
        cache_path = _write_cache(tmp_path, sample_cache)
        registry = _make_registry(config_mock, cache_path)

        info = registry.get("x_fleet.vehicle")
        assert isinstance(info.fields["name"], FieldInfo)
        assert isinstance(info.fields["fuel_cost"], FieldInfo)
        assert isinstance(info.fields["driver_id"], FieldInfo)
        assert info.fields["driver_id"].relation == "hr.employee"
        assert info.fields["x_status"].selection is not None

    def test_workflows_carried_through(self, sample_cache, config_mock, tmp_path):
        """Workflows from cache are carried into ModelInfo."""
        cache_path = _write_cache(tmp_path, sample_cache)
        registry = _make_registry(config_mock, cache_path)

        info = registry.get("x_fleet.vehicle")
        assert "action_assign" in info.workflows

    def test_access_carried_through(self, sample_cache, config_mock, tmp_path):
        """Access rights from cache are carried into ModelInfo."""
        cache_path = _write_cache(tmp_path, sample_cache)
        registry = _make_registry(config_mock, cache_path)

        info = registry.get("x_fleet.vehicle")
        assert info.access["read"] is True
        assert info.access["unlink"] is False
