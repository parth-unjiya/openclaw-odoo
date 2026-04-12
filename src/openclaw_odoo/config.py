"""Unified configuration: env vars > config file > defaults."""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

_logger = logging.getLogger("openclaw_odoo.config")


@dataclass
class AlertDestination:
    type: str  # "telegram", "webhook", "callback"
    target: str  # chat_id, URL, or function name
    events: list[str] = field(default_factory=list)
    quiet_from: Optional[str] = None  # "22:00"
    quiet_to: Optional[str] = None  # "07:00"
    timezone: str = "UTC"


@dataclass
class OdooClawConfig:
    # Odoo connection
    odoo_url: str = "http://localhost:8069"
    odoo_db: str = ""
    odoo_api_key: str = ""
    odoo_user: str = ""
    odoo_password: str = ""
    # Limits
    default_limit: int = 50
    max_limit: int = 500
    smart_fields_limit: int = 15
    # Behavior
    readonly: bool = False
    # Protocol: "auto" (detect based on version + creds), "json2", or "jsonrpc"
    protocol: str = "auto"
    # Alerts
    alerts_enabled: bool = False
    poll_interval: int = 30
    alert_destinations: list[AlertDestination] = field(default_factory=list)
    alert_thresholds: dict = field(default_factory=lambda: {
        "large_sale_order": 50000,
        "low_stock": 10
    })
    # Dynamic model registry
    model_hints: dict = field(default_factory=dict)

    def __repr__(self):
        return (f"OdooClawConfig(odoo_url={self.odoo_url!r}, odoo_db={self.odoo_db!r}, "
                f"odoo_user={self.odoo_user!r}, odoo_password='***', odoo_api_key='***')")


def load_config(config_path: Optional[str] = None) -> OdooClawConfig:
    config = OdooClawConfig()

    # Layer 1: Config file
    paths_to_try = [config_path] if config_path else [
        os.environ.get("OPENCLAW_ODOO_CONFIG"),
        str(Path.home() / ".config" / "openclaw-odoo" / "config.json"),
        "openclaw-odoo.json",
    ]
    for path in paths_to_try:
        if path and Path(path).is_file():
            try:
                with open(path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue  # skip malformed file, try next
            odoo = data.get("odoo", {})
            limits = data.get("limits", {})
            alerts = data.get("alerts", {})
            config.odoo_url = odoo.get("url", config.odoo_url)
            config.odoo_db = odoo.get("db", config.odoo_db)
            config.odoo_api_key = odoo.get("api_key", config.odoo_api_key)
            config.odoo_user = odoo.get("user", config.odoo_user)
            config.odoo_password = odoo.get("password", config.odoo_password)
            config.default_limit = limits.get("default", config.default_limit)
            config.max_limit = limits.get("max", config.max_limit)
            config.smart_fields_limit = limits.get("smart_fields", config.smart_fields_limit)
            config.readonly = data.get("readonly", config.readonly)
            config.protocol = data.get("protocol", config.protocol)
            config.alerts_enabled = alerts.get("enabled", config.alerts_enabled)
            config.poll_interval = alerts.get("poll_interval", config.poll_interval)
            # TODO: parse alert_destinations and alert_thresholds from config file
            config.model_hints = data.get("model_hints", {})
            break

    # Layer 2: Environment variables (override file)
    if url := os.environ.get("ODOO_URL"):
        config.odoo_url = url
    if db := os.environ.get("ODOO_DB"):
        config.odoo_db = db
    if key := os.environ.get("ODOO_API_KEY"):
        config.odoo_api_key = key
    if user := os.environ.get("ODOO_USER"):
        config.odoo_user = user
    if password := os.environ.get("ODOO_PASSWORD"):
        config.odoo_password = password
    if readonly := os.environ.get("OPENCLAW_ODOO_READONLY"):
        config.readonly = readonly.lower() in ("true", "1", "yes")
    if limit := os.environ.get("OPENCLAW_ODOO_DEFAULT_LIMIT"):
        try:
            config.default_limit = int(limit)
        except ValueError:
            pass  # keep existing value
    if max_limit := os.environ.get("OPENCLAW_ODOO_MAX_LIMIT"):
        try:
            config.max_limit = int(max_limit)
        except ValueError:
            pass  # keep existing value

    # Validate
    if config.default_limit < 1:
        config.default_limit = 50
    if config.max_limit < 1:
        config.max_limit = 500
    if config.default_limit > config.max_limit:
        config.default_limit = config.max_limit

    # Validate odoo_url (SSRF protection)
    parsed = urlparse(config.odoo_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid odoo_url scheme: {parsed.scheme!r}. Must be http or https.")
    if not parsed.hostname:
        raise ValueError(f"Invalid odoo_url: missing hostname in {config.odoo_url!r}")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        _logger.warning(
            "odoo_url uses HTTP (not HTTPS) for non-localhost host %s. "
            "Credentials will be transmitted in plaintext.",
            parsed.hostname,
        )

    return config
