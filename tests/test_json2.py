"""Tests for JSON-2 protocol implementation in OdooClient.

Covers protocol detection, JSON-2 execute dispatch, auth headers,
error handling (HTTP status mapping), fallback to JSON-RPC, and
protocol configuration overrides.
"""
import pytest
from unittest.mock import MagicMock, patch, call
import requests

from openclaw_odoo.client import OdooClient, _JSON2_STATUS_MAP, _IDS_METHODS
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.errors import (
    OdooAuthenticationError,
    OdooAccessError,
    OdooConnectionError,
    OdooRecordNotFoundError,
    OdooValidationError,
    OdooClawError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_key_config():
    """Config with API key set (required for JSON-2)."""
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-api-key-abc123",
        odoo_user="admin",
        odoo_password="admin",
        protocol="auto",
    )


@pytest.fixture
def no_apikey_config():
    """Config without API key (should fall back to JSON-RPC)."""
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="",
        odoo_user="admin",
        odoo_password="admin",
        protocol="auto",
    )


@pytest.fixture
def json2_client(api_key_config):
    """Client pre-configured for JSON-2 protocol (skips detection)."""
    c = OdooClient(api_key_config)
    c._uid = 2
    c._password = "admin"
    c._protocol = "json2"
    return c


@pytest.fixture
def auto_client(api_key_config):
    """Client in auto-detect mode with API key."""
    c = OdooClient(api_key_config)
    c._uid = 2
    c._password = "admin"
    return c


def _mock_session():
    """Create a mock requests.Session."""
    return MagicMock(spec=requests.Session)


def _json2_ok(result):
    """Create a mock 200 response returning JSON result."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = result
    return resp


def _json2_error(status_code, message="Error"):
    """Create a mock error response with given HTTP status."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"message": message}
    return resp


def _version_response(major, minor=0, patch_v=0, version_str=None):
    """Create a mock version endpoint response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "version": version_str or f"{major}.{minor}.{patch_v}",
        "version_info": [major, minor, patch_v],
    }
    return resp


# ===========================================================================
# 1. Protocol detection (_detect_protocol)
# ===========================================================================

class TestProtocolDetection:
    """Tests for _detect_protocol auto-detection logic."""

    def test_odoo19_with_apikey_selects_json2(self, api_key_config):
        """Odoo 19 + API key configured -> json2 protocol."""
        client = OdooClient(api_key_config)
        session = _mock_session()
        session.get.return_value = _version_response(19, 0, 0, "19.0")
        client._session = session

        client._detect_protocol()

        assert client._protocol == "json2"
        assert client._server_version == (19, 0, 0)
        session.get.assert_called_once_with(
            "http://localhost:8069/json/version", timeout=10
        )

    def test_odoo18_with_apikey_falls_back_to_jsonrpc(self, api_key_config):
        """Odoo 18 + API key -> jsonrpc (version too old)."""
        client = OdooClient(api_key_config)
        session = _mock_session()
        # /json/version returns Odoo 18
        session.get.return_value = _version_response(18, 0, 0, "18.0")
        client._session = session

        client._detect_protocol()

        assert client._protocol == "jsonrpc"

    def test_odoo19_no_apikey_falls_back_to_jsonrpc(self, no_apikey_config):
        """Odoo 19 but no API key -> jsonrpc (API key required for JSON-2)."""
        client = OdooClient(no_apikey_config)
        session = _mock_session()
        session.get.return_value = _version_response(19, 0, 0, "19.0")
        client._session = session

        client._detect_protocol()

        assert client._protocol == "jsonrpc"

    def test_json_version_404_tries_web_version(self, api_key_config):
        """/json/version returns 404 -> falls back to /web/version."""
        client = OdooClient(api_key_config)
        session = _mock_session()

        # /json/version returns 404
        not_found = MagicMock()
        not_found.status_code = 404
        # /web/version returns Odoo 19
        web_version = _version_response(19, 0, 0, "19.0")

        session.get.side_effect = [not_found, web_version]
        client._session = session

        client._detect_protocol()

        assert client._protocol == "json2"
        assert session.get.call_count == 2
        session.get.assert_any_call("http://localhost:8069/json/version", timeout=10)
        session.get.assert_any_call("http://localhost:8069/web/version", timeout=10)

    def test_both_endpoints_fail_falls_back_to_jsonrpc(self, api_key_config):
        """Both /json/version and /web/version fail -> jsonrpc fallback."""
        client = OdooClient(api_key_config)
        session = _mock_session()
        session.get.side_effect = requests.ConnectionError("Connection refused")
        client._session = session

        client._detect_protocol()

        assert client._protocol == "jsonrpc"

    def test_empty_version_info_graceful_fallback(self, api_key_config):
        """Empty version_info list -> graceful fallback to jsonrpc."""
        client = OdooClient(api_key_config)
        session = _mock_session()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"version": "unknown", "version_info": []}
        session.get.return_value = resp
        client._session = session

        # version_info[0] on empty list would raise IndexError, but
        # the default [0] in .get() handles it; version_info = [0]
        # means major version = 0 < 19 -> jsonrpc
        client._detect_protocol()

        assert client._protocol == "jsonrpc"

    def test_protocol_not_auto_skips_detection(self, api_key_config):
        """If protocol is already set (not 'auto'), skip detection entirely."""
        api_key_config.protocol = "json2"
        client = OdooClient(api_key_config)
        session = _mock_session()
        client._session = session

        client._detect_protocol()

        # Should not have made any HTTP calls
        session.get.assert_not_called()
        assert client._protocol == "json2"

    def test_web_version_returns_odoo18_with_apikey(self, api_key_config):
        """/json/version fails, /web/version returns Odoo 18 -> jsonrpc."""
        client = OdooClient(api_key_config)
        session = _mock_session()
        not_found = MagicMock()
        not_found.status_code = 404
        web_v18 = _version_response(18, 0, 0, "18.0")
        session.get.side_effect = [not_found, web_v18]
        client._session = session

        client._detect_protocol()

        assert client._protocol == "jsonrpc"


# ===========================================================================
# 2. JSON-2 execute (_execute_json2) -- method dispatch and body mapping
# ===========================================================================

class TestJson2Execute:
    """Tests for _execute_json2 method dispatch and request body construction."""

    def test_search_read_body(self, json2_client):
        """search_read: kwargs go directly into body (domain, fields, limit)."""
        session = _mock_session()
        session.post.return_value = _json2_ok([{"id": 1, "name": "Acme"}])
        json2_client._session = session

        result = json2_client.execute(
            "res.partner", "search_read",
            domain=[["is_company", "=", True]],
            fields=["name", "email"],
            limit=5,
        )

        assert result == [{"id": 1, "name": "Acme"}]
        call_args = session.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        body = call_args[1]["json"]

        assert url == "http://localhost:8069/json/2/res.partner/search_read"
        assert body["domain"] == [["is_company", "=", True]]
        assert body["fields"] == ["name", "email"]
        assert body["limit"] == 5

    def test_search_domain_in_body(self, json2_client):
        """search: first positional arg becomes domain in body."""
        session = _mock_session()
        session.post.return_value = _json2_ok([1, 2, 3])
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "search", [["active", "=", True]]
        )

        assert result == [1, 2, 3]
        body = session.post.call_args[1]["json"]
        assert body["domain"] == [["active", "=", True]]

    def test_search_count_domain_in_body(self, json2_client):
        """search_count: first positional arg becomes domain in body."""
        session = _mock_session()
        session.post.return_value = _json2_ok(42)
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "search_count", [["active", "=", True]]
        )

        assert result == 42
        body = session.post.call_args[1]["json"]
        assert body["domain"] == [["active", "=", True]]

    def test_create_vals_list_wrapping(self, json2_client):
        """create: single dict is wrapped in vals_list array."""
        session = _mock_session()
        session.post.return_value = _json2_ok([42])  # Odoo returns [id]
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "create", {"name": "New Partner", "email": "new@example.com"}
        )

        # Single create should unwrap the list -> return scalar ID
        assert result == 42
        body = session.post.call_args[1]["json"]
        assert body["vals_list"] == [{"name": "New Partner", "email": "new@example.com"}]

    def test_create_batch_returns_list(self, json2_client):
        """create: batch create (list input) returns list of IDs."""
        session = _mock_session()
        session.post.return_value = _json2_ok([42, 43])
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "create",
            [{"name": "A"}, {"name": "B"}],
        )

        assert result == [42, 43]
        body = session.post.call_args[1]["json"]
        assert body["vals_list"] == [{"name": "A"}, {"name": "B"}]

    def test_write_ids_and_vals(self, json2_client):
        """write: first arg = ids, second arg = vals."""
        session = _mock_session()
        session.post.return_value = _json2_ok(True)
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "write", [1, 2], {"name": "Updated"}
        )

        assert result is True
        body = session.post.call_args[1]["json"]
        assert body["ids"] == [1, 2]
        assert body["vals"] == {"name": "Updated"}

    def test_unlink_ids_in_body(self, json2_client):
        """unlink: first arg becomes ids in body."""
        session = _mock_session()
        session.post.return_value = _json2_ok(True)
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "unlink", [5, 6, 7]
        )

        assert result is True
        body = session.post.call_args[1]["json"]
        assert body["ids"] == [5, 6, 7]

    def test_read_ids_and_fields(self, json2_client):
        """read: ids from positional arg, fields from kwargs."""
        session = _mock_session()
        session.post.return_value = _json2_ok([{"id": 1, "name": "Test"}])
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "read", [1], fields=["name", "email"]
        )

        assert result == [{"id": 1, "name": "Test"}]
        body = session.post.call_args[1]["json"]
        assert body["ids"] == [1]
        assert body["fields"] == ["name", "email"]

    def test_fields_get_attributes(self, json2_client):
        """fields_get: attributes passed via kwargs."""
        session = _mock_session()
        session.post.return_value = _json2_ok({"name": {"type": "char", "string": "Name"}})
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "fields_get", attributes=["string", "type"]
        )

        assert "name" in result
        body = session.post.call_args[1]["json"]
        assert body["attributes"] == ["string", "type"]

    def test_read_group_mapping(self, json2_client):
        """read_group: kwargs domain/fields/groupby pass through."""
        session = _mock_session()
        session.post.return_value = _json2_ok([
            {"stage_id": [1, "New"], "stage_id_count": 5},
        ])
        json2_client._session = session

        result = json2_client._execute_json2(
            "crm.lead", "read_group",
            domain=[["active", "=", True]],
            fields=["stage_id"],
            groupby=["stage_id"],
        )

        assert len(result) == 1
        body = session.post.call_args[1]["json"]
        assert body["domain"] == [["active", "=", True]]
        assert body["fields"] == ["stage_id"]
        assert body["groupby"] == ["stage_id"]

    def test_action_confirm_ids_in_body(self, json2_client):
        """action_confirm: first positional arg becomes ids (single ID wrapped)."""
        session = _mock_session()
        session.post.return_value = _json2_ok(True)
        json2_client._session = session

        result = json2_client._execute_json2(
            "sale.order", "action_confirm", 42
        )

        assert result is True
        body = session.post.call_args[1]["json"]
        # Single int should be wrapped into a list
        assert body["ids"] == [42]
        url = session.post.call_args[0][0]
        assert url == "http://localhost:8069/json/2/sale.order/action_confirm"

    def test_write_single_id_wrapped(self, json2_client):
        """write: single int ID gets wrapped into list."""
        session = _mock_session()
        session.post.return_value = _json2_ok(True)
        json2_client._session = session

        result = json2_client._execute_json2(
            "res.partner", "write", 1, {"name": "Updated"}
        )

        body = session.post.call_args[1]["json"]
        assert body["ids"] == [1]


# ===========================================================================
# 3. Auth headers
# ===========================================================================

class TestAuthHeaders:
    """Verify Authorization and X-Odoo-Database headers on JSON-2 requests."""

    def test_bearer_token_in_authorization(self, json2_client):
        """Bearer token uses the configured API key."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2("res.partner", "search_read", domain=[])

        headers = session.post.call_args[1]["headers"]
        assert headers["Authorization"] == "bearer test-api-key-abc123"

    def test_x_odoo_database_header(self, json2_client):
        """X-Odoo-Database header is present when db is configured."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2("res.partner", "search_read", domain=[])

        headers = session.post.call_args[1]["headers"]
        assert headers["X-Odoo-Database"] == "testdb"

    def test_content_type_json(self, json2_client):
        """Content-Type is application/json with charset."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2("res.partner", "search_read", domain=[])

        headers = session.post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json; charset=utf-8"

    def test_no_db_header_when_empty(self, api_key_config):
        """X-Odoo-Database header is omitted when db is empty."""
        api_key_config.odoo_db = ""
        client = OdooClient(api_key_config)
        client._protocol = "json2"
        client._uid = 2

        session = _mock_session()
        session.post.return_value = _json2_ok([])
        client._session = session

        client._execute_json2("res.partner", "search_read", domain=[])

        headers = session.post.call_args[1]["headers"]
        assert "X-Odoo-Database" not in headers


# ===========================================================================
# 4. Error handling (HTTP status -> exception mapping)
# ===========================================================================

class TestJson2ErrorHandling:
    """Test HTTP status code to exception mapping in _execute_json2."""

    def test_401_raises_auth_error(self, json2_client):
        """HTTP 401 -> OdooAuthenticationError."""
        session = _mock_session()
        session.post.return_value = _json2_error(401, "Invalid API key")
        json2_client._session = session

        with pytest.raises(OdooAuthenticationError, match="Invalid API key"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_403_raises_access_error(self, json2_client):
        """HTTP 403 -> OdooAccessError."""
        session = _mock_session()
        session.post.return_value = _json2_error(403, "Access denied")
        json2_client._session = session

        with pytest.raises(OdooAccessError, match="Access denied"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_404_raises_not_found(self, json2_client):
        """HTTP 404 -> OdooRecordNotFoundError."""
        session = _mock_session()
        session.post.return_value = _json2_error(404, "Record not found")
        json2_client._session = session

        with pytest.raises(OdooRecordNotFoundError, match="Record not found"):
            json2_client._execute_json2("res.partner", "read", [99999])

    def test_409_raises_validation_error(self, json2_client):
        """HTTP 409 -> classify_error fallback (no direct mapping, goes to classify)."""
        session = _mock_session()
        session.post.return_value = _json2_error(409, "Conflict: duplicate record")
        json2_client._session = session

        # 409 is not in _JSON2_STATUS_MAP and < 500, so classify_error is called
        with pytest.raises(OdooClawError):
            json2_client._execute_json2("res.partner", "create", {"name": "Dup"})

    def test_422_raises_validation_error(self, json2_client):
        """HTTP 422 -> OdooValidationError."""
        session = _mock_session()
        session.post.return_value = _json2_error(422, "Validation: field 'name' required")
        json2_client._session = session

        with pytest.raises(OdooValidationError, match="field 'name' required"):
            json2_client._execute_json2("res.partner", "create", {"email": "x@x.com"})

    def test_500_raises_connection_error(self, json2_client):
        """HTTP 500 -> OdooConnectionError."""
        session = _mock_session()
        session.post.return_value = _json2_error(500, "Internal Server Error")
        json2_client._session = session

        with pytest.raises(OdooConnectionError, match="Internal Server Error"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_502_raises_connection_error(self, json2_client):
        """HTTP 502 -> OdooConnectionError (any 5xx)."""
        session = _mock_session()
        session.post.return_value = _json2_error(502, "Bad Gateway")
        json2_client._session = session

        with pytest.raises(OdooConnectionError, match="Bad Gateway"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_connection_error_raises_odoo_connection_error(self, json2_client):
        """requests.ConnectionError -> OdooConnectionError."""
        session = _mock_session()
        session.post.side_effect = requests.ConnectionError("Connection refused")
        json2_client._session = session

        with pytest.raises(OdooConnectionError, match="Connection refused"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_timeout_raises_connection_error(self, json2_client):
        """requests.Timeout -> OdooConnectionError."""
        session = _mock_session()
        session.post.side_effect = requests.Timeout("Request timed out")
        json2_client._session = session

        with pytest.raises(OdooConnectionError, match="Request timed out"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_non_json_200_raises_connection_error(self, json2_client):
        """200 response but non-JSON body -> OdooConnectionError."""
        session = _mock_session()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("No JSON")
        session.post.return_value = resp
        json2_client._session = session

        with pytest.raises(OdooConnectionError, match="Non-JSON"):
            json2_client._execute_json2("res.partner", "search_read")

    def test_error_response_without_json_body(self, json2_client):
        """Error status with non-JSON body uses default message."""
        session = _mock_session()
        resp = MagicMock()
        resp.status_code = 422
        resp.json.side_effect = ValueError("No JSON")
        session.post.return_value = resp
        json2_client._session = session

        with pytest.raises(OdooValidationError, match="HTTP 422"):
            json2_client._execute_json2("res.partner", "create", {"name": "X"})


# ===========================================================================
# 5. Fallback -- unknown method falls back to JSON-RPC
# ===========================================================================

class TestJson2Fallback:
    """Test that unknown methods fall back to _execute_jsonrpc."""

    def test_unknown_method_with_positional_args_falls_back(self, json2_client):
        """Unknown method with positional args -> falls back to _execute_jsonrpc."""
        session = _mock_session()
        # The fallback will call _execute_jsonrpc which uses /jsonrpc endpoint
        jsonrpc_resp = MagicMock()
        jsonrpc_resp.status_code = 200
        jsonrpc_resp.json.return_value = {"jsonrpc": "2.0", "result": True}
        session.post.return_value = jsonrpc_resp
        json2_client._session = session

        result = json2_client._execute_json2(
            "sale.order", "custom_wizard_method", [1, 2, 3], "extra_arg"
        )

        assert result is True
        # Verify it called /jsonrpc (not /json/2/...)
        call_url = session.post.call_args[0][0] if session.post.call_args[0] else ""
        assert "/jsonrpc" in call_url

    def test_known_method_without_args_does_not_fallback(self, json2_client):
        """search_read with only kwargs should NOT fall back to JSON-RPC."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2(
            "res.partner", "search_read", domain=[], fields=[], limit=10
        )

        call_url = session.post.call_args[0][0]
        assert "/json/2/" in call_url


# ===========================================================================
# 6. Protocol config -- forced protocol selection
# ===========================================================================

class TestProtocolConfig:
    """Test forced protocol selection via config.protocol."""

    @patch("time.sleep")  # Prevent retry delays
    def test_protocol_json2_forces_json2(self, mock_sleep, api_key_config):
        """protocol='json2' forces JSON-2 without detection."""
        api_key_config.protocol = "json2"
        client = OdooClient(api_key_config)
        client._uid = 2
        client._password = "admin"

        session = _mock_session()
        session.post.return_value = _json2_ok([{"id": 1}])
        client._session = session

        client.execute("res.partner", "search_read", domain=[], fields=["name"])

        call_url = session.post.call_args[0][0]
        assert "/json/2/res.partner/search_read" in call_url
        # No GET calls for version detection
        session.get.assert_not_called()

    @patch("time.sleep")  # Prevent retry delays
    def test_protocol_jsonrpc_forces_jsonrpc(self, mock_sleep, api_key_config):
        """protocol='jsonrpc' forces JSON-RPC without detection."""
        api_key_config.protocol = "jsonrpc"
        client = OdooClient(api_key_config)
        client._uid = 2
        client._password = "admin"

        session = _mock_session()
        jsonrpc_resp = MagicMock()
        jsonrpc_resp.status_code = 200
        jsonrpc_resp.json.return_value = {
            "jsonrpc": "2.0",
            "result": [{"id": 1, "name": "Test"}],
        }
        session.post.return_value = jsonrpc_resp
        client._session = session

        result = client.execute("res.partner", "search_read", domain=[], fields=["name"])

        assert result == [{"id": 1, "name": "Test"}]
        call_url = session.post.call_args[0][0]
        assert call_url.endswith("/jsonrpc")
        session.get.assert_not_called()

    @patch("time.sleep")
    def test_auto_protocol_triggers_detection(self, mock_sleep, api_key_config):
        """protocol='auto' triggers version detection on first execute."""
        client = OdooClient(api_key_config)
        client._uid = 2
        client._password = "admin"

        session = _mock_session()
        # GET for version detection -> Odoo 19
        version_resp = _version_response(19, 0, 0, "19.0")
        session.get.return_value = version_resp
        # POST for the actual call
        session.post.return_value = _json2_ok([{"id": 1}])
        client._session = session

        client.execute("res.partner", "search_read", domain=[])

        # Detection should have been called
        session.get.assert_called_once()
        assert client._protocol == "json2"


# ===========================================================================
# 7. URL construction
# ===========================================================================

class TestJson2UrlConstruction:
    """Verify correct URL construction for JSON-2 calls."""

    def test_url_format(self, json2_client):
        """URL follows /json/2/{model}/{method} pattern."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2("product.product", "search_read", domain=[])

        call_url = session.post.call_args[0][0]
        assert call_url == "http://localhost:8069/json/2/product.product/search_read"

    def test_url_with_dotted_model(self, json2_client):
        """Multi-level dotted model names are preserved in URL."""
        session = _mock_session()
        session.post.return_value = _json2_ok([])
        json2_client._session = session

        json2_client._execute_json2(
            "account.move.line", "search_read", domain=[]
        )

        call_url = session.post.call_args[0][0]
        assert call_url == "http://localhost:8069/json/2/account.move.line/search_read"


# ===========================================================================
# 8. Integration: execute() dispatches to correct protocol
# ===========================================================================

class TestExecuteDispatch:
    """Test that execute() dispatches to the correct protocol handler."""

    @patch("time.sleep")
    def test_execute_dispatches_to_json2(self, mock_sleep, json2_client):
        """When protocol is json2, execute() calls _execute_json2."""
        session = _mock_session()
        session.post.return_value = _json2_ok([{"id": 1}])
        json2_client._session = session

        result = json2_client.execute(
            "res.partner", "search_read", domain=[], fields=["name"]
        )

        assert result == [{"id": 1}]
        call_url = session.post.call_args[0][0]
        assert "/json/2/" in call_url

    @patch("time.sleep")
    def test_execute_validates_model_before_dispatch(self, mock_sleep, json2_client):
        """Model validation happens before protocol dispatch."""
        with pytest.raises(OdooValidationError, match="Invalid model name"):
            json2_client.execute("INVALID-MODEL!", "search_read")

    @patch("time.sleep")
    def test_execute_validates_method_before_dispatch(self, mock_sleep, json2_client):
        """Method validation happens before protocol dispatch."""
        with pytest.raises(OdooValidationError, match="Invalid method name"):
            json2_client.execute("res.partner", "DROP TABLE")

    @patch("time.sleep")
    def test_execute_blocks_dangerous_methods(self, mock_sleep, json2_client):
        """Blocked methods are rejected even with JSON-2."""
        with pytest.raises(OdooValidationError, match="blocked"):
            json2_client.execute("res.partner", "sudo")

    @patch("time.sleep")
    def test_readonly_blocks_write_via_json2(self, mock_sleep, json2_client):
        """Readonly enforcement works with JSON-2 protocol."""
        json2_client.config.readonly = True
        with pytest.raises(OdooClawError, match="READONLY"):
            json2_client.execute("res.partner", "create", {"name": "Test"})
