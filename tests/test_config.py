import json
import pytest
from openclaw_odoo.config import OdooClawConfig, load_config

def test_default_config():
    config = OdooClawConfig()
    assert config.odoo_url == "http://localhost:8069"
    assert config.odoo_db == ""
    assert config.odoo_api_key == ""
    assert config.default_limit == 50
    assert config.max_limit == 500
    assert config.smart_fields_limit == 15
    assert config.readonly is False

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "http://myodoo:8069")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_API_KEY", "secret123")
    monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
    config = load_config()
    assert config.odoo_url == "http://myodoo:8069"
    assert config.odoo_db == "testdb"
    assert config.odoo_api_key == "secret123"

def test_config_from_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "odoo": {"url": "http://file:1234", "db": "filedb", "api_key": "filekey"},
        "limits": {"default": 25, "max": 200},
        "readonly": True
    }))
    config = load_config(config_path=str(p))
    assert config.odoo_url == "http://file:1234"
    assert config.default_limit == 25
    assert config.readonly is True

def test_env_overrides_file(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"odoo": {"url": "http://file:1234"}}))
    monkeypatch.setenv("ODOO_URL", "http://env:5678")
    config = load_config(config_path=str(p))
    assert config.odoo_url == "http://env:5678"

def test_config_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    config = load_config(config_path=str(p))
    # Should fall back to defaults, not crash
    assert config.odoo_url == "http://localhost:8069"

def test_config_invalid_env_limit(monkeypatch):
    monkeypatch.setenv("OPENCLAW_ODOO_DEFAULT_LIMIT", "not_a_number")
    config = load_config()
    assert config.default_limit == 50  # keeps default


# =============================================================
# SSRF Validation
# =============================================================

class TestSSRFValidation:
    """Verify that load_config rejects non-http/https schemes and missing hostnames."""

    def test_rejects_ftp_scheme(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "ftp://evil.com")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config()

    def test_rejects_file_scheme(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "file:///etc/passwd")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config()

    def test_rejects_javascript_scheme(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "javascript:alert(1)")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config()

    def test_rejects_data_scheme(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "data:text/html,<script>alert(1)</script>")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config()

    def test_rejects_missing_hostname(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "http://")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="missing hostname"):
            load_config()

    def test_empty_url_env_ignored(self, monkeypatch):
        """Empty string is falsy in walrus operator, so env var is ignored."""
        monkeypatch.setenv("ODOO_URL", "")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        # Falls back to default (http://localhost:8069) because '' is falsy
        assert config.odoo_url == "http://localhost:8069"

    def test_accepts_http_localhost(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "http://localhost:8069")
        monkeypatch.setenv("ODOO_DB", "test")
        monkeypatch.setenv("ODOO_USER", "admin")
        monkeypatch.setenv("ODOO_PASSWORD", "admin")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.odoo_url == "http://localhost:8069"

    def test_accepts_https(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "https://odoo.example.com")
        monkeypatch.setenv("ODOO_DB", "test")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.odoo_url == "https://odoo.example.com"

    def test_accepts_https_with_port(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "https://odoo.example.com:8443")
        monkeypatch.setenv("ODOO_DB", "prod")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.odoo_url == "https://odoo.example.com:8443"

    def test_accepts_http_127_0_0_1(self, monkeypatch):
        monkeypatch.setenv("ODOO_URL", "http://127.0.0.1:5923")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.odoo_url == "http://127.0.0.1:5923"

    def test_rejects_ssrf_via_config_file(self, tmp_path, monkeypatch):
        """SSRF validation also applies to URLs loaded from config file."""
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"odoo": {"url": "gopher://internal:25"}}))
        monkeypatch.delenv("ODOO_URL", raising=False)
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        with pytest.raises(ValueError, match="Invalid odoo_url scheme"):
            load_config(config_path=str(p))


# =============================================================
# Readonly env var parsing
# =============================================================

class TestReadonlyEnvVar:
    """Verify OPENCLAW_ODOO_READONLY env var is parsed correctly."""

    def test_readonly_true(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "true")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is True

    def test_readonly_1(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "1")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is True

    def test_readonly_yes(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "yes")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is True

    def test_readonly_false(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "false")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is False

    def test_readonly_other_string(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "anything_else")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is False

    def test_readonly_TRUE_uppercase(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_READONLY", "TRUE")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.readonly is True


# =============================================================
# Limit validation edge cases
# =============================================================

class TestLimitValidation:
    """Verify that default_limit and max_limit constraints are enforced."""

    def test_negative_default_limit_reset(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_DEFAULT_LIMIT", "-5")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.default_limit == 50  # reset to 50

    def test_zero_default_limit_reset(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_DEFAULT_LIMIT", "0")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.default_limit == 50  # reset to 50

    def test_negative_max_limit_reset(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_MAX_LIMIT", "-1")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.max_limit == 500  # reset to 500

    def test_default_limit_capped_by_max(self, tmp_path, monkeypatch):
        """default_limit should be capped to max_limit if it exceeds it."""
        p = tmp_path / "config.json"
        p.write_text(json.dumps({
            "limits": {"default": 200, "max": 100}
        }))
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config(config_path=str(p))
        assert config.default_limit == 100  # capped
        assert config.max_limit == 100

    def test_invalid_max_limit_env(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ODOO_MAX_LIMIT", "not_a_number")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.max_limit == 500  # keeps default

    def test_user_password_from_env(self, monkeypatch):
        monkeypatch.setenv("ODOO_USER", "testuser")
        monkeypatch.setenv("ODOO_PASSWORD", "testpass")
        monkeypatch.delenv("OPENCLAW_ODOO_CONFIG", raising=False)
        config = load_config()
        assert config.odoo_user == "testuser"
        assert config.odoo_password == "testpass"


# =============================================================
# model_hints
# =============================================================

class TestModelHints:
    """Verify model_hints field on OdooClawConfig and config file parsing."""

    def test_default_model_hints_empty(self):
        config = OdooClawConfig()
        assert config.model_hints == {}

    def test_model_hints_from_config_file(self, tmp_path):
        p = tmp_path / "config.json"
        hints = {
            "x_fleet.vehicle": {
                "name_field": "license_plate",
                "aliases": ["fleet", "car"],
            }
        }
        p.write_text(json.dumps({"model_hints": hints}))
        config = load_config(config_path=str(p))
        assert config.model_hints == hints

    def test_model_hints_missing_defaults_to_empty(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"odoo": {"url": "http://localhost:8069"}}))
        config = load_config(config_path=str(p))
        assert config.model_hints == {}

    def test_model_hints_with_other_config(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({
            "odoo": {"url": "http://localhost:8069", "db": "testdb"},
            "model_hints": {"x_custom.model": {"label": "Custom"}},
        }))
        config = load_config(config_path=str(p))
        assert config.odoo_url == "http://localhost:8069"
        assert "x_custom.model" in config.model_hints
