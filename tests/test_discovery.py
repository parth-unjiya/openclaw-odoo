import os
import pytest
from unittest.mock import MagicMock
from openclaw_odoo.discovery import (
    scan_models, scan_fields, scan_workflows, scan_access,
    full_discovery, load_cache, save_cache, _default_cache_path,
)


@pytest.fixture
def client():
    c = MagicMock()
    c.search_read = MagicMock()
    return c


class TestScanModels:
    def test_returns_non_transient_models(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Fleet Vehicle", "model": "x_fleet.vehicle", "info": "Fleet mgmt", "modules": "x_fleet"},
            {"id": 2, "name": "Partner", "model": "res.partner", "info": "", "modules": "base"},
        ]
        result = scan_models(client)
        assert "x_fleet.vehicle" in result
        assert "res.partner" in result
        assert result["x_fleet.vehicle"]["label"] == "Fleet Vehicle"

    def test_excludes_internal_models(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Rule", "model": "ir.rule", "info": "", "modules": "base"},
            {"id": 2, "name": "Bus", "model": "bus.bus", "info": "", "modules": "bus"},
            {"id": 3, "name": "Mail", "model": "mail.message", "info": "", "modules": "mail"},
            {"id": 4, "name": "Fleet", "model": "fleet.vehicle", "info": "", "modules": "fleet"},
        ]
        result = scan_models(client)
        assert "ir.rule" not in result
        assert "bus.bus" not in result
        assert "mail.message" not in result
        assert "fleet.vehicle" in result  # third-party addon kept


class TestScanFields:
    def test_returns_field_defs_with_extended_attrs(self, client):
        client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name", "required": True, "readonly": False, "store": True},
            "driver_id": {"type": "many2one", "string": "Driver", "relation": "hr.employee", "required": False, "readonly": False, "store": True},
            "x_status": {"type": "selection", "string": "Status", "selection": [["available", "Available"]], "required": False, "readonly": False, "store": True},
        }
        result = scan_fields(client, ["x_fleet.vehicle"])
        assert "x_fleet.vehicle" in result
        fields = result["x_fleet.vehicle"]
        assert fields["name"]["type"] == "char"
        assert fields["driver_id"]["relation"] == "hr.employee"
        assert fields["x_status"]["selection"] == [["available", "Available"]]

    def test_parallel_calls_multiple_models(self, client):
        client.fields_get.return_value = {"name": {"type": "char", "string": "Name", "store": True}}
        result = scan_fields(client, ["model.a", "model.b", "model.c"])
        assert len(result) == 3
        assert client.fields_get.call_count == 3


class TestScanWorkflows:
    def test_discovers_server_actions(self, client):
        client.search_read.side_effect = [
            # ir.actions.server query
            [
                {"id": 1, "name": "Assign Vehicle", "binding_model_id": [10, "x_fleet.vehicle"], "state": "code"},
                {"id": 2, "name": "Return Vehicle", "binding_model_id": [10, "x_fleet.vehicle"], "state": "code"},
            ],
        ]
        result = scan_workflows(client, ["x_fleet.vehicle"])
        assert "x_fleet.vehicle" in result
        assert len(result["x_fleet.vehicle"]) >= 2

    def test_infers_from_state_field(self, client):
        # No server actions found
        client.search_read.return_value = []
        # But model has a state selection field
        fields = {
            "state": {
                "type": "selection",
                "selection": [["draft", "Draft"], ["confirmed", "Confirmed"], ["done", "Done"]],
                "store": True,
            }
        }
        result = scan_workflows(client, ["x_custom.order"], fields_by_model={"x_custom.order": fields})
        wf = result.get("x_custom.order", [])
        assert "action_confirm" in wf or "action_done" in wf


class TestScanAccess:
    def test_returns_crud_booleans(self, client):
        # check_access_rights returns True/False
        client.execute.return_value = True
        result = scan_access(client, ["x_fleet.vehicle"])
        assert "x_fleet.vehicle" in result
        access = result["x_fleet.vehicle"]
        assert "read" in access
        assert "write" in access
        assert "create" in access
        assert "unlink" in access


class TestFullDiscovery:
    def test_full_discovery_saves_cache(self, client, tmp_path):
        client.search_read.side_effect = [
            # scan_models
            [{"id": 1, "name": "Fleet", "model": "x_fleet.vehicle", "info": "", "modules": "x_fleet"}],
            # scan_workflows (ir.actions.server)
            [],
        ]
        client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name", "required": True, "store": True},
        }
        client.execute.return_value = True  # access rights
        client.base_url = "http://localhost:8069"
        client.config = MagicMock()
        client.config.odoo_db = "testdb"

        cache_path = tmp_path / "cache.json"
        result = full_discovery(client, cache_path=str(cache_path))

        assert "x_fleet.vehicle" in result["models"]
        assert cache_path.exists()

        loaded = load_cache(str(cache_path))
        assert loaded["models"]["x_fleet.vehicle"]["label"] == "Fleet"


# =============================================================
# Gap 1: scan_fields / scan_access exception paths
# =============================================================

class TestScanFieldsErrors:
    def test_fields_get_exception_returns_empty(self, client):
        """When fields_get raises, return empty dict for that model."""
        client.fields_get.side_effect = Exception("access denied")
        result = scan_fields(client, ["x_broken.model"])
        assert result["x_broken.model"] == {}


class TestScanAccessErrors:
    def test_execute_exception_returns_false(self, client):
        """When check_access_rights raises, return False for all ops."""
        client.execute.side_effect = Exception("denied")
        result = scan_access(client, ["x_broken.model"])
        assert result["x_broken.model"] == {
            "read": False, "write": False, "create": False, "unlink": False,
        }


# =============================================================
# Gap 2: save_cache direct tests
# =============================================================

class TestSaveCache:
    def test_saves_valid_json(self, tmp_path):
        data = {"version": "1.0", "models": {"test.model": {"label": "Test"}}}
        path = save_cache(data, str(tmp_path / "test_cache.json"))
        loaded = load_cache(path)
        assert loaded["models"]["test.model"]["label"] == "Test"

    def test_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "cache.json")
        save_cache({"version": "1.0"}, path)
        assert os.path.exists(path)


# =============================================================
# Gap 3: load_cache with corrupt / missing JSON
# =============================================================

class TestLoadCacheErrors:
    def test_corrupt_json_returns_none(self, tmp_path):
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{broken json!!!")
        assert load_cache(str(bad_file)) is None

    def test_missing_file_returns_none(self):
        assert load_cache("/nonexistent/path/cache.json") is None


# =============================================================
# Gap 5: Empty Odoo instance discovery
# =============================================================

class TestEmptyOdooInstance:
    def test_scan_models_empty_returns_empty(self, client):
        client.search_read.return_value = []
        result = scan_models(client)
        assert result == {}

    def test_full_discovery_empty_instance(self, client, tmp_path):
        client.search_read.return_value = []
        client.fields_get.return_value = {}
        client.execute.return_value = True
        client.base_url = "http://localhost:8069"
        client.config = MagicMock()
        client.config.odoo_db = "empty_db"
        cache_path = tmp_path / "cache.json"
        result = full_discovery(client, str(cache_path))
        assert result["model_count"] == 0
        assert result["models"] == {}
