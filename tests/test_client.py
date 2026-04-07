import pytest
from unittest.mock import patch, MagicMock
from openclaw_odoo.client import OdooClient
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.errors import OdooAuthenticationError, OdooClawError


@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_user="admin",
        odoo_password="admin",
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    # Pre-set auth to skip authenticate call in tests
    c._uid = 2
    c._password = "admin"
    return c


def test_client_init(config):
    c = OdooClient(config)
    assert c.config == config
    assert c.base_url == "http://localhost:8069"
    assert c._fields_cache == {}
    assert c._uid is None


def test_client_web_url(client):
    url = client.web_url("res.partner", 42)
    assert url == "http://localhost:8069/odoo/res.partner/42"


def test_client_requires_credentials():
    config = OdooClawConfig(odoo_api_key="", odoo_user="", odoo_password="")
    c = OdooClient(config)
    with pytest.raises(OdooAuthenticationError):
        c._ensure_auth()


def test_authenticate_success(config):
    c = OdooClient(config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": 2}
    c._session = MagicMock()
    c._session.post.return_value = mock_resp

    c._ensure_auth()
    assert c._uid == 2


def test_authenticate_failure(config):
    c = OdooClient(config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": False}
    c._session = MagicMock()
    c._session.post.return_value = mock_resp

    with pytest.raises(OdooAuthenticationError, match="invalid credentials"):
        c._ensure_auth()


def test_execute_calls_jsonrpc(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": [{"id": 1, "name": "Test"}]}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    result = client.execute("res.partner", "search_read",
                            [[["is_company", "=", True]]],
                            {"fields": ["name"], "limit": 5})
    assert result == [{"id": 1, "name": "Test"}]
    # Verify JSON-RPC payload structure
    call_args = mock_session.post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    assert payload["method"] == "call"
    assert payload["params"]["service"] == "object"
    assert payload["params"]["method"] == "execute_kw"
    assert payload["params"]["args"][3] == "res.partner"
    assert payload["params"]["args"][4] == "search_read"


def test_search_read(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": [{"id": 1, "name": "Acme"}]}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    results = client.search_read("res.partner",
                                 domain=[["is_company", "=", True]],
                                 fields=["name"], limit=5)
    assert len(results) == 1
    assert results[0]["name"] == "Acme"


def test_fields_cache(client):
    cache_key = ("res.partner", ("string", "type", "required", "readonly", "relation"))
    client._fields_cache[cache_key] = {"name": {"type": "char"}}
    result = client.fields_get("res.partner")
    assert "name" in result


def test_readonly_blocks_create(client):
    client.config.readonly = True
    with pytest.raises(OdooClawError, match="READONLY"):
        client.create("res.partner", {"name": "Test"})


def test_readonly_blocks_write(client):
    client.config.readonly = True
    with pytest.raises(OdooClawError, match="READONLY"):
        client.write("res.partner", [1], {"name": "Test"})


def test_readonly_blocks_unlink(client):
    client.config.readonly = True
    with pytest.raises(OdooClawError, match="READONLY"):
        client.unlink("res.partner", [1])


def test_execute_handles_api_error(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "error": {"message": "ValidationError: field 'name' is required"}
    }
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    from openclaw_odoo.errors import OdooValidationError
    with pytest.raises(OdooValidationError):
        client.execute("res.partner", "create", {"email": "test@test.com"})


def test_execute_handles_server_error(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    from openclaw_odoo.errors import OdooConnectionError
    with pytest.raises(OdooConnectionError, match="Server error 502"):
        client.execute("res.partner", "search_read")


def test_execute_handles_non_json(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("No JSON")
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    from openclaw_odoo.errors import OdooConnectionError
    with pytest.raises(OdooConnectionError, match="Non-JSON"):
        client.execute("res.partner", "search_read")


def _get_sent_kwargs(mock_session):
    """Extract the kwargs dict sent in the execute_kw JSON-RPC payload."""
    call_args = mock_session.post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    return payload["params"]["args"][6]


def test_search_enforces_max_limit(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session
    client.config.max_limit = 100

    client.search_read("res.partner", limit=9999)
    sent_kwargs = _get_sent_kwargs(mock_session)
    assert sent_kwargs["limit"] <= 100


def test_search_read_limit_none_fetches_all(client):
    """limit=None should omit the limit key so Odoo returns all records."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    client.search_read("res.partner", limit=None)
    sent_kwargs = _get_sent_kwargs(mock_session)
    assert "limit" not in sent_kwargs


def test_search_read_limit_zero_fetches_all(client):
    """limit=0 should also omit the limit key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    client.search_read("res.partner", limit=0)
    sent_kwargs = _get_sent_kwargs(mock_session)
    assert "limit" not in sent_kwargs


def test_search_read_omitted_limit_uses_default(client):
    """Omitting limit should apply default_limit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session
    client.config.default_limit = 50

    client.search_read("res.partner")
    sent_kwargs = _get_sent_kwargs(mock_session)
    assert sent_kwargs["limit"] == 50


def test_search_limit_none_fetches_all(client):
    """search() with limit=None should omit the limit key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jsonrpc": "2.0", "result": []}
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    client._session = mock_session

    client.search("res.partner", limit=None)
    sent_kwargs = _get_sent_kwargs(mock_session)
    assert "limit" not in sent_kwargs
