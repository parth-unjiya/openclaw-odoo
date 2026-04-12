"""Agent 20-22 COMBINED: Config, Fields, Batch tests.

Tests for:
  - openclaw_odoo.config: load_config, OdooClawConfig
  - openclaw_odoo.fields: select_smart_fields
  - openclaw_odoo.batch: batch_execute
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from openclaw_odoo.config import OdooClawConfig, load_config
from openclaw_odoo.fields import select_smart_fields
from openclaw_odoo.batch import batch_execute
from openclaw_odoo.errors import OdooClawError


# ============================================================
# Fixtures
# ============================================================

CONFIG_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "openclaw-odoo.json"
)

# Realistic res.partner-like field definitions for Fields tests
PARTNER_FIELDS_DEF = {
    "id": {"type": "integer", "string": "ID", "required": True},
    "name": {"type": "char", "string": "Name", "required": True},
    "display_name": {"type": "char", "string": "Display Name"},
    "email": {"type": "char", "string": "Email"},
    "phone": {"type": "char", "string": "Phone"},
    "active": {"type": "boolean", "string": "Active"},
    "state": {"type": "selection", "string": "Status"},
    "partner_id": {"type": "many2one", "string": "Related Partner"},
    "company_id": {"type": "many2one", "string": "Company"},
    "user_id": {"type": "many2one", "string": "Salesperson"},
    "date": {"type": "date", "string": "Date"},
    "create_date": {"type": "datetime", "string": "Created on"},
    "write_date": {"type": "datetime", "string": "Last Updated"},
    "amount_total": {"type": "monetary", "string": "Total Amount"},
    "country_id": {"type": "many2one", "string": "Country"},
    "street": {"type": "char", "string": "Street"},
    "city": {"type": "char", "string": "City"},
    "zip": {"type": "char", "string": "Zip"},
    "state_id": {"type": "many2one", "string": "State"},
    "vat": {"type": "char", "string": "Tax ID"},
    "website": {"type": "char", "string": "Website"},
    "comment": {"type": "html", "string": "Notes"},
    "title": {"type": "many2one", "string": "Title"},
    # Should be excluded:
    "image_1920": {"type": "binary", "string": "Image"},
    "image_128": {"type": "image", "string": "Image 128"},
    "message_ids": {"type": "one2many", "string": "Messages"},
    "message_follower_ids": {"type": "one2many", "string": "Followers"},
    "activity_ids": {"type": "one2many", "string": "Activities"},
    "__last_update": {"type": "datetime", "string": "Last Modified"},
}


# ============================================================
# 1. Config: load_config from JSON file
# ============================================================

class TestConfigLoadFromFile:
    """Test 1: load_config from the project's openclaw-odoo.json file."""

    def test_load_config_from_project_file(self, monkeypatch):
        """Load the actual project config file and verify values match."""
        # Clear env vars so they don't override file values
        for var in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD",
                     "ODOO_API_KEY", "OPENCLAW_ODOO_READONLY",
                     "OPENCLAW_ODOO_DEFAULT_LIMIT", "OPENCLAW_ODOO_MAX_LIMIT",
                     "OPENCLAW_ODOO_CONFIG"):
            monkeypatch.delenv(var, raising=False)

        config = load_config(config_path=CONFIG_FILE_PATH)

        assert config.odoo_url == "http://localhost:8069"
        assert config.odoo_db == "openclaw_odoo_db"
        assert config.odoo_user == "admin"
        assert config.odoo_password == "admin"
        assert config.default_limit == 50
        assert config.max_limit == 500
        assert config.smart_fields_limit == 15
        assert config.readonly is False
        assert config.alerts_enabled is False


# ============================================================
# 2. Config: Env var override
# ============================================================

class TestConfigEnvVarOverride:
    """Test 2: Environment variable overrides config file values."""

    def test_env_var_overrides_odoo_url(self, monkeypatch):
        """Set ODOO_URL=http://localhost:9999, load_config, verify override."""
        monkeypatch.setenv("ODOO_URL", "http://localhost:9999")
        # Clear env vars that could interfere
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        monkeypatch.delenv("ODOO_DB", raising=False)

        config = load_config(config_path=CONFIG_FILE_PATH)

        # Env var should override the file's http://localhost:8069
        assert config.odoo_url == "http://localhost:9999"
        # Other file values should remain
        assert config.odoo_db == "openclaw_odoo_db"


# ============================================================
# 3. Config: Readonly flag
# ============================================================

class TestConfigReadonlyFlag:
    """Test 3: OPENCLAW_ODOO_READONLY=true sets readonly."""

    def test_readonly_env_true(self, monkeypatch):
        """Set OPENCLAW_ODOO_READONLY=true and verify config.readonly is True."""
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "true")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)

        config = load_config(config_path=CONFIG_FILE_PATH)

        assert config.readonly is True


# ============================================================
# 4. Config: URL validation -- ftp scheme
# ============================================================

class TestConfigUrlValidation:
    """Test 4: ftp://localhost should raise ValueError."""

    def test_ftp_url_raises_value_error(self, monkeypatch):
        """An ftp:// scheme is not allowed and should raise ValueError."""
        monkeypatch.setenv("ODOO_URL", "ftp://localhost")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)

        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config()


# ============================================================
# 5. Config: repr masks password
# ============================================================

class TestConfigRepr:
    """Test 5: Config repr should mask password and api_key."""

    def test_password_masked_in_repr(self):
        """Verify password and api_key appear as '***' in repr."""
        config = OdooClawConfig(
            odoo_url="http://localhost:8069",
            odoo_db="testdb",
            odoo_user="admin",
            odoo_password="super_secret_password",
            odoo_api_key="top_secret_key",
        )
        r = repr(config)

        assert "super_secret_password" not in r
        assert "top_secret_key" not in r
        assert "odoo_password='***'" in r
        assert "odoo_api_key='***'" in r
        assert "odoo_url='http://localhost:8069'" in r
        assert "odoo_db='testdb'" in r
        assert "odoo_user='admin'" in r


# ============================================================
# 6. Fields: select_smart_fields returns ~15 fields
# ============================================================

class TestFieldsSmartSelection:
    """Test 6: select_smart_fields on partner-like fields_def returns ~15 fields."""

    def test_smart_fields_returns_about_15(self):
        """Default limit=15 should return at most 15 fields."""
        fields = select_smart_fields(PARTNER_FIELDS_DEF)

        assert isinstance(fields, list)
        assert len(fields) <= 15
        assert len(fields) > 0
        # High-importance fields should be present
        assert "id" in fields
        assert "name" in fields
        assert "email" in fields
        assert "display_name" in fields


# ============================================================
# 7. Fields: select_smart_fields with limit=5
# ============================================================

class TestFieldsLimit:
    """Test 7: select_smart_fields with limit=5 returns exactly 5."""

    def test_smart_fields_limit_5(self):
        """Limit=5 should return at most 5 fields."""
        fields = select_smart_fields(PARTNER_FIELDS_DEF, limit=5)

        assert len(fields) == 5
        # The top 5 should all be high-importance fields
        for f in fields:
            assert isinstance(f, str)


# ============================================================
# 8. Fields: No binary/o2m fields in result
# ============================================================

class TestFieldsExclusions:
    """Test 8: Binary, image, and one2many fields are excluded."""

    def test_no_binary_or_o2m_fields(self):
        """Excluded types (binary, image, one2many) must not appear."""
        fields = select_smart_fields(PARTNER_FIELDS_DEF, limit=50)

        # binary/image
        assert "image_1920" not in fields
        assert "image_128" not in fields
        # one2many
        assert "message_ids" not in fields
        assert "message_follower_ids" not in fields
        assert "activity_ids" not in fields
        # internal
        assert "__last_update" not in fields


# ============================================================
# 9. Fields: Edge case -- empty fields_def
# ============================================================

class TestFieldsEmptyInput:
    """Test 9: select_smart_fields({}) returns empty list."""

    def test_empty_fields_def(self):
        """Empty input should return an empty list without errors."""
        fields = select_smart_fields({})

        assert fields == []

    def test_empty_fields_def_with_limit(self):
        """Empty input with explicit limit should still return empty list."""
        fields = select_smart_fields({}, limit=10)

        assert fields == []


# ============================================================
# 10. Batch: 3 search operations all succeed
# ============================================================

class TestBatchAllSucceed:
    """Test 10: batch_execute with 3 search operations, all succeeding."""

    def test_three_searches_all_succeed(self):
        """All 3 search operations should succeed with correct result structure."""
        mock_client = MagicMock()
        mock_client.config.readonly = False
        mock_client.execute.side_effect = [
            [1, 2, 3],          # first search_read result
            [4, 5],             # second search_read result
            [{"id": 6}],       # third search_read result
        ]

        ops = [
            {
                "model": "res.partner",
                "method": "search_read",
                "args": [],
                "kwargs": {"domain": [("active", "=", True)], "fields": ["name"]},
            },
            {
                "model": "sale.order",
                "method": "search_read",
                "args": [],
                "kwargs": {"domain": [], "fields": ["name", "state"]},
            },
            {
                "model": "product.product",
                "method": "search_read",
                "args": [],
                "kwargs": {"domain": [], "fields": ["name", "list_price"]},
            },
        ]

        result = batch_execute(mock_client, ops)

        assert result["success"] is True
        assert result["total"] == 3
        assert result["succeeded"] == 3
        assert result["failed"] == 0
        assert len(result["results"]) == 3
        # Verify each result has correct structure
        for i, res in enumerate(result["results"]):
            assert res["index"] == i
            assert res["success"] is True
        assert result["results"][0]["result"] == [1, 2, 3]
        assert result["results"][1]["result"] == [4, 5]
        assert result["results"][2]["result"] == [{"id": 6}]


# ============================================================
# 11. Batch: Failing op with fail_fast=True
# ============================================================

class TestBatchFailFast:
    """Test 11: batch_execute with failing op and fail_fast=True stops early."""

    def test_fail_fast_stops_on_error(self):
        """Second op fails -- third op should NOT execute."""
        mock_client = MagicMock()
        mock_client.config.readonly = False
        mock_client.execute.side_effect = [
            [1, 2],                              # first succeeds
            OdooClawError("Validation failed"),   # second fails
            [3, 4],                              # third would succeed (never called)
        ]

        ops = [
            {"model": "res.partner", "method": "search_read", "args": []},
            {"model": "sale.order", "method": "create", "args": [{"name": "Bad"}]},
            {"model": "product.product", "method": "search_read", "args": []},
        ]

        result = batch_execute(mock_client, ops, fail_fast=True)

        assert result["success"] is False
        assert result["total"] == 3
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        # Only 2 results: first succeeded, second failed, third never ran
        assert len(result["results"]) == 2
        assert result["results"][0]["success"] is True
        assert result["results"][1]["success"] is False
        assert "Validation failed" in result["results"][1]["error"]
        # execute should have been called only twice
        assert mock_client.execute.call_count == 2


# ============================================================
# 12. Batch: Failing op with fail_fast=False
# ============================================================

class TestBatchContinueOnError:
    """Test 12: batch_execute with failing op and fail_fast=False continues."""

    def test_continue_on_error(self):
        """Second op fails -- third op should still execute."""
        mock_client = MagicMock()
        mock_client.config.readonly = False
        mock_client.execute.side_effect = [
            [1, 2],                              # first succeeds
            OdooClawError("Something went wrong"),  # second fails
            [3, 4],                              # third succeeds
        ]

        ops = [
            {"model": "res.partner", "method": "search_read", "args": []},
            {"model": "sale.order", "method": "create", "args": [{"name": "Bad"}]},
            {"model": "product.product", "method": "search_read", "args": []},
        ]

        result = batch_execute(mock_client, ops, fail_fast=False)

        assert result["success"] is False  # has failures
        assert result["total"] == 3
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        # All 3 results present
        assert len(result["results"]) == 3
        assert result["results"][0]["success"] is True
        assert result["results"][1]["success"] is False
        assert result["results"][2]["success"] is True
        assert result["results"][2]["result"] == [3, 4]
        # execute was called 3 times
        assert mock_client.execute.call_count == 3


# ============================================================
# 13. Batch: Empty operations list
# ============================================================

class TestBatchEmptyOperations:
    """Test 13: batch_execute with empty operations list."""

    def test_empty_operations(self):
        """Empty operations list should return success with zero counts."""
        mock_client = MagicMock()
        mock_client.config.readonly = False

        result = batch_execute(mock_client, [])

        assert result["success"] is True
        assert result["total"] == 0
        assert result["succeeded"] == 0
        assert result["failed"] == 0
        assert result["results"] == []
        # execute should never be called
        mock_client.execute.assert_not_called()
