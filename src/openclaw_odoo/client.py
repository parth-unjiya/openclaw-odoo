"""OdooClient -- Dual-protocol Odoo API connection (JSON-2 for Odoo 19+, JSON-RPC fallback)."""
import logging
import re
import threading
from typing import Any, Optional
import requests

from .config import OdooClawConfig
from .errors import (
    OdooClawError, OdooConnectionError, OdooAuthenticationError,
    OdooAccessError, OdooValidationError, OdooRecordNotFoundError,
    classify_error
)
from .retry import with_retry

logger = logging.getLogger("openclaw_odoo")

# JSON-2 HTTP status → exception mapping
_JSON2_STATUS_MAP = {
    401: OdooAuthenticationError,
    403: OdooAccessError,
    404: OdooRecordNotFoundError,
    409: OdooValidationError,
    422: OdooValidationError,
}

# Methods where positional args map to 'ids' in JSON-2
_IDS_METHODS = frozenset({
    "read", "write", "unlink",
    "action_confirm", "action_cancel", "action_post",
    "action_draft", "action_done",
    "action_set_won", "action_set_lost",
    "action_quotation_send", "action_send_mail",
    "action_invoice_sent", "action_create_payments",
    "action_approve", "action_submit_expenses",
    "button_confirm", "button_cancel",
})

# Methods allowed in readonly mode (everything else is blocked)
_READ_METHODS = frozenset({
    "search", "search_read", "search_count", "read", "fields_get",
    "name_get", "name_search", "check_access_rights", "check_access_rule",
    "read_group", "get_views", "onchange", "default_get",
})

# Methods blocked even in non-readonly mode (dangerous internal methods)
_BLOCKED_METHODS = frozenset({
    # Client-level blocks (env/sudo/private ORM internals)
    "sudo", "with_user", "with_env", "with_context",
    "_sql", "_write", "_create", "_read", "_unlink",
    "load", "import_data", "copy_data",
    # Interface-level blocks (DDL/shell/destructive)
    "unlink_all", "init", "shell",
    "_init_column", "_auto_init", "_table_exist", "_create_table",
    # Module management -- can crash or compromise the server
    "button_immediate_install", "button_immediate_upgrade",
    "button_immediate_uninstall",
    "button_install", "button_upgrade", "button_uninstall",
    "module_install", "module_uninstall",
    # ORM internals that can execute arbitrary code
    "_register_hook", "_setup_complete", "_setup_base",
})

# Methods that mutate data -- blocked when client is in readonly mode.
_WRITE_METHODS = frozenset({
    "create", "write", "unlink", "action_confirm", "action_cancel",
    "action_post", "action_draft", "action_done",
})

# Input validation patterns (from odoo-mcp-gateway)
_MODEL_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_METHOD_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

_UNSET = object()  # sentinel: "caller did not pass a limit argument"


class OdooClient:
    def __init__(self, config: OdooClawConfig):
        self.config = config
        self.base_url = config.odoo_url.rstrip("/")
        self._session = requests.Session()
        self._fields_cache: dict[str, dict] = {}
        self._uid: Optional[int] = None
        self._rpc_id: int = 0
        self._password: Optional[str] = None
        self._lock = threading.RLock()
        # Protocol: "auto" (detect), "json2", or "jsonrpc"
        self._protocol: str = getattr(config, "protocol", "auto")
        self._server_version: Optional[tuple] = None

    def __repr__(self):
        return f"OdooClient(url={self.base_url!r}, db={self.config.odoo_db!r}, uid={self._uid})"

    def close(self):
        """Close the underlying HTTP session."""
        self._password = None
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _next_id(self) -> int:
        with self._lock:
            self._rpc_id += 1
            return self._rpc_id

    def web_url(self, model: str, record_id: int) -> str:
        """Build the Odoo web URL for a specific record."""
        return f"{self.base_url}/odoo/{model}/{record_id}"

    def _ensure_auth(self):
        """Authenticate via JSON-RPC if not already done.

        Uses double-checked locking to prevent concurrent threads from
        triggering duplicate authentication requests.
        """
        if self._uid is not None:
            return
        with self._lock:
            if self._uid is not None:
                return
            if not self.config.odoo_user or not self.config.odoo_password:
                if not self.config.odoo_api_key:
                    raise OdooAuthenticationError(
                        "No credentials configured. Set ODOO_USER+ODOO_PASSWORD or ODOO_API_KEY."
                    )
                # API key mode: authenticate with key as password
                self._authenticate(self.config.odoo_api_key, self.config.odoo_api_key)
            else:
                self._authenticate(self.config.odoo_user, self.config.odoo_password)

    def _authenticate(self, login: str, password: str):
        """Call /jsonrpc to authenticate and get UID."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": self._next_id(),
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [self.config.odoo_db, login, password, {}]
            }
        }
        try:
            resp = self._session.post(
                f"{self.base_url}/jsonrpc",
                json=payload, timeout=30
            )
        except requests.ConnectionError as e:
            raise OdooConnectionError(str(e))
        except requests.Timeout as e:
            raise OdooConnectionError(str(e))

        if resp.status_code >= 500:
            raise OdooConnectionError(f"Server error {resp.status_code}")

        try:
            data = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            raise OdooConnectionError(f"Non-JSON response (status {resp.status_code})")

        if "error" in data:
            raise OdooAuthenticationError(
                data["error"].get("message", str(data["error"]))
            )

        uid = data.get("result")
        if not uid:
            raise OdooAuthenticationError("Authentication failed: invalid credentials")
        self._uid = uid
        # Store password for execute_kw calls
        self._password = password
        logger.info("Authenticated as UID %d on %s", uid, self.config.odoo_db)

    def _detect_protocol(self):
        """Auto-detect whether the server supports JSON-2 (Odoo 19+)."""
        if self._protocol != "auto":
            return
        try:
            resp = self._session.get(
                f"{self.base_url}/json/version", timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                version_info = data.get("version_info", [0])
                self._server_version = tuple(version_info[:3])
                if (version_info[0] if version_info else 0) >= 19 and self.config.odoo_api_key:
                    self._protocol = "json2"
                    if not self.config.odoo_db:
                        logger.warning("JSON-2 protocol selected but odoo_db is empty — X-Odoo-Database header will be omitted")
                    logger.info(
                        "Odoo %s detected with API key — using JSON-2 protocol",
                        data.get("version", "19+"),
                    )
                    return
        except Exception:
            pass
        # Fallback: try /web/version (works on all versions)
        try:
            resp = self._session.get(
                f"{self.base_url}/web/version", timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                version_info = data.get("version_info", [0])
                self._server_version = tuple(version_info[:3])
                if (version_info[0] if version_info else 0) >= 19 and self.config.odoo_api_key:
                    self._protocol = "json2"
                    if not self.config.odoo_db:
                        logger.warning("JSON-2 protocol selected but odoo_db is empty — X-Odoo-Database header will be omitted")
                    logger.info(
                        "Odoo %s detected with API key — using JSON-2 protocol",
                        data.get("version", "19+"),
                    )
                    return
        except Exception:
            pass
        self._protocol = "jsonrpc"
        logger.info("Using JSON-RPC protocol (Odoo < 19 or no API key)")

    def _execute_json2(self, model: str, method: str, *args, **kwargs) -> Any:
        """Execute via Odoo 19+ JSON-2 API: POST /json/2/<model>/<method>."""
        url = f"{self.base_url}/json/2/{model}/{method}"
        headers = {
            "Authorization": f"bearer {self.config.odoo_api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.config.odoo_db:
            headers["X-Odoo-Database"] = self.config.odoo_db

        # Convert positional args to named params for JSON-2
        body = dict(kwargs)
        if args:
            if method in _IDS_METHODS and args:
                # First positional arg is IDs for write/unlink/action methods
                body["ids"] = args[0] if isinstance(args[0], list) else [args[0]]
                if method == "write" and len(args) > 1:
                    body["vals"] = args[1]
            elif method == "create" and args:
                vals = args[0]
                body["vals_list"] = vals if isinstance(vals, list) else [vals]
            elif method in ("search", "search_count") and args:
                body["domain"] = args[0]
            elif method == "read_group" and args:
                if len(args) >= 1:
                    body["domain"] = args[0]
                if len(args) >= 2:
                    body["fields"] = args[1]
                if len(args) >= 3:
                    body["groupby"] = args[2]
            elif method == "fields_get":
                pass  # kwargs already has 'attributes'
            else:
                # Generic fallback: can't map positional args for unknown methods
                # Fall back to JSON-RPC for this call
                return self._execute_jsonrpc(model, method, *args, **kwargs)

        try:
            resp = self._session.post(url, json=body, headers=headers, timeout=30)
        except requests.ConnectionError as e:
            raise OdooConnectionError(str(e), model=model, method=method)
        except requests.Timeout as e:
            raise OdooConnectionError(str(e), model=model, method=method)

        # JSON-2 uses proper HTTP status codes
        if resp.status_code == 200:
            try:
                result = resp.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                raise OdooConnectionError(
                    f"Non-JSON response (status {resp.status_code})",
                    model=model, method=method,
                )
            # Handle batch create returning list
            if method == "create" and isinstance(result, list) and len(result) == 1:
                return result[0]  # Return single ID for single create
            return result

        # Error response
        try:
            error_data = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            error_data = {}

        error_msg = error_data.get("message", f"HTTP {resp.status_code}")
        exc_class = _JSON2_STATUS_MAP.get(resp.status_code)
        if exc_class:
            raise exc_class(error_msg, model=model, method=method)
        if resp.status_code >= 500:
            raise OdooConnectionError(error_msg, model=model, method=method)
        raise classify_error(error_msg, model=model, method=method)

    @with_retry(max_retries=3, base_delay=1.0)
    def execute(self, model: str, method: str, *args, **kwargs) -> Any:
        """Call an Odoo model method via the best available protocol.

        Automatically uses JSON-2 (Odoo 19+) when an API key is configured,
        falling back to JSON-RPC for older versions or user/password auth.

        Args:
            model: Odoo model name (e.g. 'res.partner').
            method: Model method to call (e.g. 'search_read').
            *args: Positional arguments forwarded to the method.
            **kwargs: Keyword arguments forwarded to the method.

        Returns:
            The result from Odoo.

        Raises:
            OdooValidationError: If model or method name is invalid.
            OdooClawError: If readonly mode blocks a write method.
        """
        # Validate model and method names to prevent injection
        if not _MODEL_RE.match(model) or len(model) > 128:
            raise OdooValidationError(
                f"Invalid model name: {model!r}", model=model, method=method
            )
        if not _METHOD_RE.match(method) or len(method) > 128:
            raise OdooValidationError(
                f"Invalid method name: {method!r}", model=model, method=method
            )

        # Block dangerous internal methods (even in non-readonly mode)
        if method in _BLOCKED_METHODS:
            raise OdooValidationError(
                f"Method {method!r} is blocked for security reasons",
                model=model, method=method,
            )

        # Enforce readonly at the execute level (covers all code paths)
        if self.config.readonly and method not in _READ_METHODS:
            raise OdooClawError(
                f"Cannot call {model}.{method}() in READONLY mode",
                model=model, method=method,
            )

        # Auto-detect protocol on first call (double-checked locking)
        if self._protocol == "auto":
            with self._lock:
                if self._protocol == "auto":
                    self._detect_protocol()

        # Dispatch to the right protocol
        if self._protocol == "json2":
            return self._execute_json2(model, method, *args, **kwargs)
        return self._execute_jsonrpc(model, method, *args, **kwargs)

    def _execute_jsonrpc(self, model: str, method: str, *args, **kwargs) -> Any:
        """Execute via legacy JSON-RPC protocol (Odoo < 19 or user/password auth)."""
        self._ensure_auth()
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": self._next_id(),
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.config.odoo_db,
                    self._uid,
                    self._password,
                    model,
                    method,
                    list(args),
                    kwargs,
                ]
            }
        }
        try:
            resp = self._session.post(
                f"{self.base_url}/jsonrpc",
                json=payload, timeout=30
            )
        except requests.ConnectionError as e:
            raise OdooConnectionError(str(e), model=model, method=method)
        except requests.Timeout as e:
            raise OdooConnectionError(str(e), model=model, method=method)

        if resp.status_code >= 500:
            raise OdooConnectionError(
                f"Server error {resp.status_code}", model=model, method=method
            )

        try:
            data = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            raise OdooConnectionError(
                f"Non-JSON response (status {resp.status_code})", model=model, method=method
            )

        if "error" in data:
            error_data = data["error"]
            nested_data = error_data.get("data", {})
            # Prefer the detailed nested message over the generic top-level one
            error_msg = nested_data.get("message") or error_data.get("message", str(error_data))
            # Check for access denied specifically
            fault = nested_data.get("name", "")
            if "AccessDenied" in fault or "AccessError" in fault:
                raise OdooAccessError(error_msg, model=model, method=method)
            raise classify_error(error_msg, model=model, method=method)
        return data.get("result", data)

    def search_read(self, model: str, domain: Optional[list] = None,
                    fields: Optional[list] = None, limit=_UNSET,
                    offset: int = 0, order: Optional[str] = None) -> list[dict]:
        """Search records and return their field values in one call.

        Args:
            model: Odoo model name.
            domain: Odoo domain filter list.
            fields: Fields to return (empty list = all).
            limit: Maximum records to return.  Omit (or pass ``_UNSET``) to
                use ``config.default_limit``; pass ``None`` or ``0`` to fetch
                *all* records; any positive int is capped at ``config.max_limit``.
            offset: Number of records to skip.
            order: Sort expression (e.g. 'name asc').

        Returns:
            List of record dicts.
        """
        domain = domain or []
        kwargs: dict[str, Any] = {
            "domain": domain, "fields": fields or [],
            "offset": offset,
        }
        if limit is _UNSET:
            kwargs["limit"] = min(self.config.default_limit, self.config.max_limit)
        elif limit:
            if isinstance(limit, int) and limit < 0:
                raise OdooValidationError(f"Invalid limit: {limit} (must be non-negative)")
            kwargs["limit"] = min(limit, self.config.max_limit)
        # limit=None or limit=0 → no limit key → Odoo returns all records
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", **kwargs)

    def search(self, model: str, domain: Optional[list] = None,
               limit=_UNSET, offset: int = 0,
               order: Optional[str] = None) -> list[int]:
        """Search for record IDs matching the domain.

        Args:
            model: Odoo model name.
            domain: Odoo domain filter list.
            limit: Maximum IDs to return.  Omit to use
                ``config.default_limit``; pass ``None`` or ``0`` to fetch all;
                any positive int is capped at ``config.max_limit``.
            offset: Number of records to skip.
            order: Sort expression.

        Returns:
            List of integer record IDs.
        """
        domain = domain or []
        kwargs: dict[str, Any] = {
            "domain": domain, "offset": offset,
        }
        if limit is _UNSET:
            kwargs["limit"] = min(self.config.default_limit, self.config.max_limit)
        elif limit:
            if isinstance(limit, int) and limit < 0:
                raise OdooValidationError(f"Invalid limit: {limit} (must be non-negative)")
            kwargs["limit"] = min(limit, self.config.max_limit)
        # limit=None or limit=0 → no limit key → Odoo returns all records
        if order:
            kwargs["order"] = order
        return self.execute(model, "search", **kwargs)

    def search_count(self, model: str, domain: Optional[list] = None) -> int:
        """Return the count of records matching the domain."""
        return self.execute(model, "search_count", domain or [])

    def create(self, model: str, values: dict) -> int:
        """Create a new record and return its ID.

        Raises:
            OdooClawError: If client is in readonly mode.
        """
        if self.config.readonly:
            raise OdooClawError("Cannot create records in READONLY mode")
        return self.execute(model, "create", values)

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        """Update existing records by IDs.

        Raises:
            OdooClawError: If client is in readonly mode.
        """
        if self.config.readonly:
            raise OdooClawError("Cannot write records in READONLY mode")
        return self.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        """Delete records by IDs.

        Raises:
            OdooClawError: If client is in readonly mode.
        """
        if self.config.readonly:
            raise OdooClawError("Cannot delete records in READONLY mode")
        return self.execute(model, "unlink", ids)

    def read(self, model: str, ids: list[int],
             fields: Optional[list] = None) -> list[dict]:
        """Read specific records by their IDs."""
        return self.execute(model, "read", ids, fields=fields or [])

    def fields_get(self, model: str,
                   attributes: Optional[list] = None) -> dict:
        """Retrieve field definitions for a model (cached).

        Args:
            model: Odoo model name.
            attributes: Field attributes to retrieve (e.g. 'string', 'type').

        Returns:
            Dict mapping field names to their attribute dicts.
        """
        attrs = attributes or [
            "string", "type", "required", "readonly", "relation"
        ]
        cache_key = (model, tuple(attrs))
        with self._lock:
            if cache_key in self._fields_cache:
                return self._fields_cache[cache_key]
        result = self.execute(
            model, "fields_get", attributes=attrs
        )
        with self._lock:
            self._fields_cache[cache_key] = result
        return result
