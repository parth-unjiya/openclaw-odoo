"""Tests for security fixes applied 2026-03-17.

Covers:
- Readonly allowlist enforcement in execute() (S1/S2/S3/S4/S5)
- Model/method regex validation (injection prevention)
- Error sanitization in skill interface
- Session close/context manager (Q6)
- Protected json.loads in skill main() (Q11)
- limit=None and limit=0 handling (Q3/Q12/Q16)
- File path validation (S8/S9)
- MCP error sanitization (S10)
- Batch readonly enforcement
"""
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from openclaw_odoo.client import OdooClient, _READ_METHODS, _MODEL_RE, _METHOD_RE
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.errors import OdooClawError, OdooValidationError


# =============================================================
# Fixtures
# =============================================================

@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_user="admin",
        odoo_password="admin",
    )


@pytest.fixture
def readonly_config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_user="admin",
        odoo_password="admin",
        readonly=True,
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    c._uid = 2
    c._password = "admin"
    return c


@pytest.fixture
def readonly_client(readonly_config):
    c = OdooClient(readonly_config)
    c._uid = 2
    c._password = "admin"
    return c


def _mock_session(client):
    """Attach a mock session that returns empty success responses."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session
    return mock_session


# =============================================================
# 1. Readonly allowlist enforcement in execute()
# =============================================================

class TestReadonlyAllowlist:
    """Verify that readonly mode blocks write methods at the execute() level."""

    def test_read_methods_allowed_in_readonly(self, readonly_client):
        """All _READ_METHODS should pass the readonly check (fail at RPC, not readonly)."""
        _mock_session(readonly_client)
        for method in ["search_read", "search", "search_count", "read",
                       "fields_get", "name_get", "read_group"]:
            result = readonly_client.execute("res.partner", method)
            # If we get here without OdooClawError, the readonly check passed

    def test_create_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("res.partner", "create", {"name": "x"})

    def test_write_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("res.partner", "write", [1], {"name": "x"})

    def test_unlink_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("res.partner", "unlink", [1])

    def test_action_confirm_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("sale.order", "action_confirm", [1])

    def test_action_post_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("account.move", "action_post", [1])

    def test_button_confirm_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("purchase.order", "button_confirm", [1])

    def test_action_cancel_blocked_in_readonly(self, readonly_client):
        with pytest.raises(OdooClawError, match="READONLY"):
            readonly_client.execute("sale.order", "action_cancel", [1])

    def test_write_methods_allowed_when_not_readonly(self, client):
        """Write methods should work normally when readonly is False."""
        _mock_session(client)
        client.execute("sale.order", "action_confirm", [1])  # should not raise


# =============================================================
# 2. Model/method regex validation
# =============================================================

class TestInputValidation:
    """Verify model and method name regex validation prevents injection."""

    def test_valid_model_names(self, client):
        _mock_session(client)
        for model in ["res.partner", "sale.order.line", "x_custom.model",
                       "hr.employee", "account.move"]:
            client.execute(model, "search_read")  # should not raise

    def test_valid_method_names(self, client):
        _mock_session(client)
        for method in ["search_read", "fields_get", "name_get",
                        "action_confirm", "_compute_amount"]:
            client.execute("res.partner", method)  # should not raise

    def test_invalid_model_with_sql_injection(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("res.partner; DROP TABLE", "search_read")

    def test_invalid_model_with_path_traversal(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("../etc/passwd", "search_read")

    def test_invalid_model_uppercase(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("RES.PARTNER", "search_read")

    def test_invalid_model_empty(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("", "search_read")

    def test_invalid_model_too_long(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("a" * 129, "search_read")

    def test_invalid_model_starts_with_digit(self, client):
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            client.execute("123.model", "search_read")

    def test_invalid_method_with_semicolon(self, client):
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            client.execute("res.partner", "search_read; DROP TABLE")

    def test_invalid_method_empty(self, client):
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            client.execute("res.partner", "")

    def test_invalid_method_too_long(self, client):
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            client.execute("res.partner", "a" * 129)

    def test_invalid_method_starts_with_digit(self, client):
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            client.execute("res.partner", "123method")

    def test_invalid_method_uppercase(self, client):
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            client.execute("res.partner", "SearchRead")

    def test_validation_runs_before_auth(self):
        """Validation should reject bad input even without authentication."""
        config = OdooClawConfig(odoo_user="", odoo_password="", odoo_api_key="")
        c = OdooClient(config)
        # This should fail at validation, NOT at auth
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            c.execute("BAD MODEL", "search_read")


# =============================================================
# 3. Session close / context manager
# =============================================================

class TestSessionLifecycle:
    def test_close_calls_session_close(self, config):
        c = OdooClient(config)
        c._session = MagicMock()
        c.close()
        c._session.close.assert_called_once()

    def test_context_manager_calls_close(self, config):
        with OdooClient(config) as c:
            c._session = MagicMock()
            session = c._session
        session.close.assert_called_once()

    def test_context_manager_closes_on_exception(self, config):
        session = MagicMock()
        try:
            with OdooClient(config) as c:
                c._session = session
                raise ValueError("test error")
        except ValueError:
            pass
        session.close.assert_called_once()


# =============================================================
# 4. Error sanitization
# =============================================================

class TestErrorSanitization:
    def test_strips_tracebacks(self):
        from openclaw_odoo.interfaces.openclaw_skill import _sanitize_error
        raw = 'Traceback (most recent call last):\n  File "/odoo/models.py", line 42\nValueError: bad'
        result = _sanitize_error(raw)
        assert "Traceback" not in result
        assert "/odoo/models.py" not in result

    def test_strips_file_paths(self):
        from openclaw_odoo.interfaces.openclaw_skill import _sanitize_error
        raw = "Error at /home/user/odoo/addons/sale/models.py:142 in create"
        result = _sanitize_error(raw)
        assert "/home/user" not in result
        assert ".py:142" not in result

    def test_strips_sql(self):
        from openclaw_odoo.interfaces.openclaw_skill import _sanitize_error
        raw = "ProgrammingError: SELECT id, name FROM res_partner WHERE active = true"
        result = _sanitize_error(raw)
        assert "SELECT" not in result
        assert "res_partner" not in result

    def test_fallback_message_when_all_stripped(self):
        from openclaw_odoo.interfaces.openclaw_skill import _sanitize_error
        raw = 'Traceback (most recent call last):\n  File "/app/server.py", line 1, in main\n    raise Exception()'
        result = _sanitize_error(raw)
        assert result == "An internal error occurred"

    def test_clean_message_passes_through(self):
        from openclaw_odoo.interfaces.openclaw_skill import _sanitize_error
        raw = "Partner 42 not found"
        result = _sanitize_error(raw)
        assert result == "Partner 42 not found"

    def test_route_action_uses_sanitization(self):
        from openclaw_odoo.interfaces.openclaw_skill import route_action
        mock_client = MagicMock()
        mock_client.create.side_effect = Exception(
            'Traceback (most recent call last):\n  File "/odoo/server.py", line 1\nSELECT * FROM secret_table WHERE 1=1'
        )
        result = route_action(mock_client, "create_partner", {"name": "Test"})
        assert result["error"] is True
        assert "Traceback" not in result["message"]
        assert "SELECT" not in result["message"]
        assert "secret_table" not in result["message"]


# =============================================================
# 5. Protected json.loads in skill main()
# =============================================================

class TestSkillMainJsonProtection:
    @patch("openclaw_odoo.interfaces.openclaw_skill.load_config")
    @patch("openclaw_odoo.interfaces.openclaw_skill.OdooClient")
    def test_invalid_json_returns_error(self, MockClient, mock_load_config):
        from openclaw_odoo.interfaces.openclaw_skill import main
        mock_load_config.return_value = MagicMock()
        MockClient.return_value = MagicMock()

        with patch("sys.stdin", StringIO("not valid json at all")), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            main()
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed["error"] is True
            assert parsed["message"] == "Invalid JSON input"
            assert parsed["action"] == ""

    @patch("openclaw_odoo.interfaces.openclaw_skill.load_config")
    @patch("openclaw_odoo.interfaces.openclaw_skill.OdooClient")
    def test_empty_input_returns_error(self, MockClient, mock_load_config):
        from openclaw_odoo.interfaces.openclaw_skill import main
        mock_load_config.return_value = MagicMock()
        MockClient.return_value = MagicMock()

        with patch("sys.stdin", StringIO("")), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            main()
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed["error"] is True

    @patch("openclaw_odoo.interfaces.openclaw_skill.load_config")
    @patch("openclaw_odoo.interfaces.openclaw_skill.OdooClient")
    def test_truncated_json_returns_error(self, MockClient, mock_load_config):
        from openclaw_odoo.interfaces.openclaw_skill import main
        mock_load_config.return_value = MagicMock()
        MockClient.return_value = MagicMock()

        with patch("sys.stdin", StringIO('{"action": "search"')), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            main()
            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed["error"] is True


# =============================================================
# 6. limit=None and limit=0 handling
# =============================================================

class TestLimitHandling:
    """Verify limit handling: None/0 omit limit (fetch all), _UNSET uses default, positive ints are capped."""

    def test_limit_none_omits_limit(self, client):
        """limit=None should omit the limit key so Odoo returns all records."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50
        client.config.max_limit = 500

        client.search_read("res.partner", limit=None)
        payload = mock_session.post.call_args[1]["json"]
        sent_kwargs = payload["params"]["args"][6]
        assert "limit" not in sent_kwargs

    def test_limit_zero_omits_limit(self, client):
        """limit=0 should omit the limit key so Odoo returns all records."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50
        client.config.max_limit = 500

        client.search_read("res.partner", limit=0)
        payload = mock_session.post.call_args[1]["json"]
        sent_kwargs = payload["params"]["args"][6]
        assert "limit" not in sent_kwargs

    def test_omitted_limit_uses_default(self, client):
        """Omitting limit (uses _UNSET sentinel) should apply min(default_limit, max_limit)."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50
        client.config.max_limit = 500

        client.search_read("res.partner")
        payload = mock_session.post.call_args[1]["json"]
        sent_kwargs = payload["params"]["args"][6]
        assert sent_kwargs["limit"] == 50

    def test_explicit_limit_respected(self, client):
        """An explicit limit should be used as-is (capped by max_limit)."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50
        client.config.max_limit = 500

        client.search_read("res.partner", limit=200)
        payload = mock_session.post.call_args[1]["json"]
        sent_limit = payload["params"]["args"][6]["limit"]
        assert sent_limit == 200

    def test_explicit_limit_capped_by_max(self, client):
        """A limit exceeding max_limit should be capped."""
        mock_session = _mock_session(client)
        client.config.max_limit = 100

        client.search_read("res.partner", limit=9999)
        payload = mock_session.post.call_args[1]["json"]
        sent_limit = payload["params"]["args"][6]["limit"]
        assert sent_limit == 100

    def test_search_limit_none_omits_limit(self, client):
        """search() with limit=None should omit the limit key."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50

        client.search("res.partner", limit=None)
        payload = mock_session.post.call_args[1]["json"]
        sent_kwargs = payload["params"]["args"][6]
        assert "limit" not in sent_kwargs

    def test_search_limit_zero_omits_limit(self, client):
        """search() with limit=0 should omit the limit key."""
        mock_session = _mock_session(client)
        client.config.default_limit = 50
        client.config.max_limit = 500

        client.search("res.partner", limit=0)
        payload = mock_session.post.call_args[1]["json"]
        sent_kwargs = payload["params"]["args"][6]
        assert "limit" not in sent_kwargs


# =============================================================
# 7. File path validation (_validate_filepath)
# =============================================================

class TestFilePathValidation:
    """Verify _validate_filepath blocks traversal, symlinks, and bad extensions."""

    def test_rejects_path_traversal(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        with pytest.raises(OdooClawError, match="Path traversal"):
            _validate_filepath("../../etc/passwd.csv", "read")

    def test_rejects_absolute_path_with_traversal(self):
        """Absolute paths with .. resolve via normpath; traversal or not-found is raised."""
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        # /tmp/safe/../../../etc/shadow.csv normalizes to /etc/shadow.csv (no .. remains)
        # so it passes the traversal check but fails as File not found or bad extension.
        # Relative paths with .. are the real traversal risk.
        with pytest.raises(OdooClawError):
            _validate_filepath("/tmp/safe/../../../etc/shadow.csv", "read")

    def test_rejects_bad_extension_py(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(OdooClawError, match="Unsupported file extension"):
                _validate_filepath(path, "read")
        finally:
            os.unlink(path)

    def test_rejects_bad_extension_sh(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(OdooClawError, match="Unsupported file extension"):
                _validate_filepath(path, "read")
        finally:
            os.unlink(path)

    def test_rejects_bad_extension_json(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(OdooClawError, match="Unsupported file extension"):
                _validate_filepath(path, "read")
        finally:
            os.unlink(path)

    def test_rejects_empty_path(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        with pytest.raises(OdooClawError, match="File path is required"):
            _validate_filepath("", "read")

    def test_rejects_none_path(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        with pytest.raises(OdooClawError, match="File path is required"):
            _validate_filepath(None, "read")

    def test_rejects_non_string_path(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        with pytest.raises(OdooClawError, match="File path is required"):
            _validate_filepath(12345, "read")

    def test_rejects_symlink(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        import os
        real_file = tmp_path / "real.csv"
        real_file.write_text("a,b,c")
        symlink = tmp_path / "link.csv"
        os.symlink(str(real_file), str(symlink))
        with pytest.raises(OdooClawError, match="Symbolic links"):
            _validate_filepath(str(symlink), "read")

    def test_accepts_valid_csv(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        real_file = tmp_path / "data.csv"
        real_file.write_text("name,email")
        result = _validate_filepath(str(real_file), "read")
        assert result.endswith("data.csv")

    def test_accepts_valid_xlsx(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        real_file = tmp_path / "data.xlsx"
        real_file.write_bytes(b"dummy xlsx content")
        result = _validate_filepath(str(real_file), "read")
        assert result.endswith("data.xlsx")

    def test_accepts_valid_xls(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        real_file = tmp_path / "data.xls"
        real_file.write_bytes(b"dummy xls content")
        result = _validate_filepath(str(real_file), "read")
        assert result.endswith("data.xls")

    def test_rejects_nonexistent_read(self):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        with pytest.raises(OdooClawError, match="File not found"):
            _validate_filepath("/tmp/nonexistent_file_abc123.csv", "read")

    def test_allows_nonexistent_write(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        path = str(tmp_path / "output.csv")
        result = _validate_filepath(path, "write")
        assert result.endswith("output.csv")

    def test_write_mode_does_not_require_file_existence(self, tmp_path):
        from openclaw_odoo.intelligence.file_import import _validate_filepath
        path = str(tmp_path / "new_export.xlsx")
        result = _validate_filepath(path, "write")
        assert result.endswith("new_export.xlsx")


# =============================================================
# 8. MCP error sanitization
# =============================================================

class TestMCPErrorSanitization:
    """Verify MCP server tools sanitize internal error details."""

    def test_mcp_sanitize_error_strips_traceback(self):
        from openclaw_odoo.interfaces.mcp_server import _sanitize_error
        raw = 'Traceback (most recent call last):\n  File "/odoo/models.py", line 42\nValueError: bad'
        result = _sanitize_error(raw)
        assert "Traceback" not in result
        assert "/odoo/models.py" not in result

    def test_mcp_sanitize_error_strips_file_paths(self):
        from openclaw_odoo.interfaces.mcp_server import _sanitize_error
        raw = "Error at /home/user/odoo/addons/sale/models.py:142 in create"
        result = _sanitize_error(raw)
        assert "/home/user" not in result
        assert ".py:142" not in result

    def test_mcp_sanitize_error_strips_sql(self):
        from openclaw_odoo.interfaces.mcp_server import _sanitize_error
        raw = "ProgrammingError: SELECT id, name FROM res_partner WHERE active = true"
        result = _sanitize_error(raw)
        assert "SELECT" not in result
        assert "res_partner" not in result

    def test_mcp_sanitize_error_fallback(self):
        from openclaw_odoo.interfaces.mcp_server import _sanitize_error
        raw = 'Traceback (most recent call last):\n  File "/app/server.py", line 1\n  raise Exception()'
        result = _sanitize_error(raw)
        assert result == "An internal error occurred"

    def test_mcp_sanitize_error_clean_passthrough(self):
        from openclaw_odoo.interfaces.mcp_server import _sanitize_error
        raw = "Record not found"
        result = _sanitize_error(raw)
        assert result == "Record not found"

    @pytest.mark.anyio
    async def test_mcp_search_records_sanitizes_on_error(self):
        """search_records tool should return sanitized error, not raw traceback."""
        from openclaw_odoo.interfaces.mcp_server import create_mcp_server
        mock_client = MagicMock()
        mock_client.config = MagicMock()
        mock_client.config.odoo_url = "http://localhost:8069"
        mock_client.config.odoo_db = "test_db"
        mock_client.config.readonly = False
        mock_client.search_read.side_effect = Exception(
            'Traceback (most recent call last):\n  File "/odoo/server.py"\nSELECT * FROM secret'
        )
        mcp = create_mcp_server(mock_client)
        result = await mcp.call_tool("search_records", {"model": "res.partner"})
        text = result.content[0].text
        data = json.loads(text)
        assert "error" in data
        assert "Traceback" not in data["error"]
        assert "SELECT" not in data["error"]
        assert "secret" not in data["error"]

    @pytest.mark.anyio
    async def test_mcp_create_record_sanitizes_on_error(self):
        """create_record tool should return sanitized error, not raw traceback."""
        from openclaw_odoo.interfaces.mcp_server import create_mcp_server
        mock_client = MagicMock()
        mock_client.config = MagicMock()
        mock_client.config.odoo_url = "http://localhost:8069"
        mock_client.config.odoo_db = "test_db"
        mock_client.config.readonly = False
        mock_client.create.side_effect = Exception(
            'File "/odoo/models.py", line 100\nINSERT INTO res_partner (name) VALUES (\'test\')'
        )
        mcp = create_mcp_server(mock_client)
        result = await mcp.call_tool("create_record", {
            "model": "res.partner",
            "values": {"name": "Test"},
        })
        text = result.content[0].text
        data = json.loads(text)
        assert "error" in data
        assert "INSERT INTO" not in data["error"]
        assert "/odoo/models.py" not in data["error"]

    @pytest.mark.anyio
    async def test_mcp_update_record_sanitizes_on_error(self):
        """update_record tool should return sanitized error."""
        from openclaw_odoo.interfaces.mcp_server import create_mcp_server
        mock_client = MagicMock()
        mock_client.config = MagicMock()
        mock_client.config.odoo_url = "http://localhost:8069"
        mock_client.config.odoo_db = "test_db"
        mock_client.config.readonly = False
        mock_client.write.side_effect = Exception(
            'Traceback (most recent call last):\n  File "/odoo/api.py", line 55'
        )
        mcp = create_mcp_server(mock_client)
        result = await mcp.call_tool("update_record", {
            "model": "res.partner",
            "record_id": 1,
            "values": {"name": "X"},
        })
        text = result.content[0].text
        data = json.loads(text)
        assert "error" in data
        assert "Traceback" not in data["error"]


# =============================================================
# 9. Batch readonly enforcement
# =============================================================

class TestBatchReadonlyEnforcement:
    """Verify that batch operations respect readonly mode via client.execute()."""

    def test_batch_blocks_create_in_readonly(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        operations = [
            {"model": "res.partner", "method": "create", "args": [{"name": "Test"}]},
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["success"] is False
        assert result["failed"] == 1
        assert "READONLY" in result["results"][0]["error"]

    def test_batch_blocks_write_in_readonly(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        operations = [
            {"model": "res.partner", "method": "write", "args": [[1], {"name": "X"}]},
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["success"] is False
        assert result["failed"] == 1
        assert "READONLY" in result["results"][0]["error"]

    def test_batch_blocks_unlink_in_readonly(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        operations = [
            {"model": "res.partner", "method": "unlink", "args": [[1]]},
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["success"] is False
        assert result["failed"] == 1
        assert "READONLY" in result["results"][0]["error"]

    def test_batch_blocks_action_confirm_in_readonly(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        operations = [
            {"model": "sale.order", "method": "action_confirm", "args": [[1]]},
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["success"] is False
        assert "READONLY" in result["results"][0]["error"]

    def test_batch_allows_read_in_readonly(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        _mock_session(readonly_client)
        operations = [
            {"model": "res.partner", "method": "search_read"},
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["success"] is True
        assert result["succeeded"] == 1

    def test_batch_fail_fast_stops_on_first_error(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        _mock_session(readonly_client)
        operations = [
            {"model": "res.partner", "method": "search_read"},  # OK
            {"model": "res.partner", "method": "create", "args": [{"name": "X"}]},  # BLOCKED
            {"model": "res.partner", "method": "search_read"},  # should not run
        ]
        result = batch_execute(readonly_client, operations, fail_fast=True)
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        # Only 2 operations attempted (fail_fast stopped before 3rd)
        assert len(result["results"]) == 2

    def test_batch_no_fail_fast_continues_after_error(self, readonly_client):
        from openclaw_odoo.batch import batch_execute
        _mock_session(readonly_client)
        operations = [
            {"model": "res.partner", "method": "search_read"},  # OK
            {"model": "res.partner", "method": "create", "args": [{"name": "X"}]},  # BLOCKED
            {"model": "res.partner", "method": "search_read"},  # should still run
        ]
        result = batch_execute(readonly_client, operations, fail_fast=False)
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        assert len(result["results"]) == 3


# =============================================================
# 10. Client read() and search_count() coverage
# =============================================================

class TestClientReadAndSearchCount:
    """Cover client.read() and client.search_count() which had zero coverage."""

    def test_read_sends_correct_payload(self, client):
        mock_session = _mock_session(client)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "result": [{"id": 1, "name": "Acme"}],
        }
        mock_session.post.return_value = mock_resp

        result = client.read("res.partner", [1], fields=["name"])
        assert result == [{"id": 1, "name": "Acme"}]

        # Verify payload structure
        payload = mock_session.post.call_args[1]["json"]
        assert payload["params"]["args"][3] == "res.partner"
        assert payload["params"]["args"][4] == "read"
        assert payload["params"]["args"][5] == [[1]]

    def test_read_with_no_fields(self, client):
        mock_session = _mock_session(client)
        client.read("res.partner", [1, 2])
        payload = mock_session.post.call_args[1]["json"]
        # fields kwarg should be empty list
        assert payload["params"]["args"][6].get("fields") == []

    def test_search_count_returns_int(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": 42}
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        client._session = mock_session

        result = client.search_count("res.partner", [["is_company", "=", True]])
        assert result == 42

    def test_search_count_empty_domain(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": 0}
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        client._session = mock_session

        result = client.search_count("res.partner")
        assert result == 0


# =============================================================
# 11. Client API-key auth path
# =============================================================

class TestAPIKeyAuth:
    """Cover the API-key authentication branch in _ensure_auth."""

    def test_api_key_auth_uses_key_as_both_login_and_password(self):
        config = OdooClawConfig(
            odoo_url="http://localhost:8069",
            odoo_db="testdb",
            odoo_user="",
            odoo_password="",
            odoo_api_key="my_secret_key",
        )
        c = OdooClient(config)

        # Mock the session to return a successful auth response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": 99}
        c._session = MagicMock()
        c._session.post.return_value = mock_resp

        c._ensure_auth()

        assert c._uid == 99
        # Verify authenticate was called with api_key as both login and password
        call_payload = c._session.post.call_args[1]["json"]
        auth_args = call_payload["params"]["args"]
        assert auth_args[1] == "my_secret_key"  # login
        assert auth_args[2] == "my_secret_key"  # password

    def test_no_credentials_raises_auth_error(self):
        from openclaw_odoo.errors import OdooAuthenticationError
        config = OdooClawConfig(
            odoo_url="http://localhost:8069",
            odoo_db="testdb",
            odoo_user="",
            odoo_password="",
            odoo_api_key="",
        )
        c = OdooClient(config)
        with pytest.raises(OdooAuthenticationError, match="No credentials"):
            c._ensure_auth()


# =============================================================
# 12. Client connection error handling
# =============================================================

class TestClientConnectionErrors:
    """Cover exception handling paths in client.execute() and _authenticate()."""

    def test_execute_connection_error(self, client):
        import requests as req
        client._session = MagicMock()
        client._session.post.side_effect = req.ConnectionError("refused")
        from openclaw_odoo.errors import OdooConnectionError
        with pytest.raises(OdooConnectionError, match="refused"):
            client.execute("res.partner", "search_read")

    def test_execute_timeout_error(self, client):
        import requests as req
        client._session = MagicMock()
        client._session.post.side_effect = req.Timeout("timed out")
        from openclaw_odoo.errors import OdooConnectionError
        with pytest.raises(OdooConnectionError, match="timed out"):
            client.execute("res.partner", "search_read")

    def test_execute_server_error_500(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        client._session = MagicMock()
        client._session.post.return_value = mock_resp
        from openclaw_odoo.errors import OdooConnectionError
        with pytest.raises(OdooConnectionError, match="Server error 500"):
            client.execute("res.partner", "search_read")

    def test_execute_non_json_response(self, client):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("No JSON")
        client._session = MagicMock()
        client._session.post.return_value = mock_resp
        from openclaw_odoo.errors import OdooConnectionError
        with pytest.raises(OdooConnectionError, match="Non-JSON response"):
            client.execute("res.partner", "search_read")

    def test_execute_odoo_error_response(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "error": {
                "message": "ValidationError: Missing required field",
                "data": {"name": "ValidationError"},
            }
        }
        client._session = MagicMock()
        client._session.post.return_value = mock_resp
        with pytest.raises(OdooClawError):
            client.execute("res.partner", "search_read")

    def test_execute_access_denied_response(self, client):
        from openclaw_odoo.errors import OdooAccessError
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "error": {
                "message": "AccessDenied",
                "data": {"name": "AccessDenied"},
            }
        }
        client._session = MagicMock()
        client._session.post.return_value = mock_resp
        with pytest.raises(OdooAccessError):
            client.execute("res.partner", "search_read")
