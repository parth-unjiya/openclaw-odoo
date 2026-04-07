"""Odoo instance schema discovery engine.

Performs Level 3 scans: models, fields, workflows, access rights.
Results are cached to ~/.config/openclaw-odoo/schema_cache.json.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import OdooClient

logger = logging.getLogger("openclaw_odoo.discovery")

# Internal framework model prefixes -- excluded from discovery.
_EXCLUDED_PREFIXES = (
    "ir.", "base.", "bus.", "mail.", "_unknown", "base_import.",
    "web_editor.", "web_tour.", "report.", "digest.",
)

# Extended attributes for fields_get (includes store + selection).
_FIELD_ATTRIBUTES = [
    "string", "type", "required", "readonly",
    "relation", "relation_field", "store", "selection",
]


def scan_models(client: OdooClient) -> dict[str, dict]:
    """Fetch all non-transient, non-internal models from ir.model."""
    raw = client.search_read(
        "ir.model",
        domain=[("transient", "=", False)],
        fields=["name", "model", "info", "modules"],
        limit=None,
    )
    result: dict[str, dict] = {}
    for rec in raw:
        model_name = rec.get("model", "")
        if not model_name:
            continue
        if any(model_name.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        result[model_name] = {
            "label": rec.get("name", model_name),
            "module": rec.get("modules", ""),
            "description": rec.get("info", "") or "",
        }
    return result


def scan_fields(client: OdooClient, model_names: list[str],
                max_workers: int = 10) -> dict[str, dict]:
    """Fetch field definitions for each model using extended attributes.

    Uses ThreadPoolExecutor for parallel fields_get calls.
    """
    result: dict[str, dict] = {}

    def _get_fields(model: str) -> tuple[str, dict]:
        try:
            fields = client.fields_get(model, attributes=_FIELD_ATTRIBUTES)
            # Filter to stored fields only (skip computed)
            stored = {}
            for fname, fdef in fields.items():
                if fname.startswith("__"):
                    continue
                stored[fname] = {
                    "type": fdef.get("type", ""),
                    "string": fdef.get("string", fname),
                    "required": fdef.get("required", False),
                    "readonly": fdef.get("readonly", False),
                    "relation": fdef.get("relation"),
                    "selection": fdef.get("selection"),
                    "store": fdef.get("store", True),
                }
            return model, stored
        except Exception:
            logger.warning("Failed to get fields for %s", model)
            return model, {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_get_fields, m): m for m in model_names}
        for future in as_completed(futures):
            model, fields = future.result()
            result[model] = fields

    return result


# Common state-to-action mappings for inference
_STATE_ACTION_MAP = {
    "confirmed": "action_confirm",
    "confirm": "action_confirm",
    "done": "action_done",
    "cancel": "action_cancel",
    "cancelled": "action_cancel",
    "draft": "action_draft",
    "approved": "action_approve",
    "posted": "action_post",
    "sent": "action_send",
}


def scan_workflows(client: OdooClient, model_names: list[str],
                   fields_by_model: dict[str, dict] | None = None) -> dict[str, list[str]]:
    """Discover workflow actions per model.

    Phase 1: ir.actions.server + state field inference.
    """
    result: dict[str, list[str]] = {m: [] for m in model_names}

    # 1. Query ir.actions.server for bound actions
    try:
        actions = client.search_read(
            "ir.actions.server",
            domain=[("binding_model_id", "!=", False)],
            fields=["name", "binding_model_id", "state"],
            limit=None,
        )
        for action in actions:
            binding = action.get("binding_model_id")
            if isinstance(binding, (list, tuple)) and len(binding) > 1:
                model_name = binding[1]  # name from many2one
                # Try to match to a technical name
                for m in model_names:
                    if m == model_name or m.replace(".", " ").title().replace(" ", "") in model_name.replace(".", ""):
                        result[m].append(action.get("name", ""))
                        break
    except Exception:
        logger.warning("Failed to scan ir.actions.server")

    # 2. Infer from state/status selection fields
    if fields_by_model:
        for model, fields in fields_by_model.items():
            if model not in result:
                continue
            for fname in ("state", "status", "x_status", "x_state"):
                fdef = fields.get(fname, {})
                if fdef.get("type") == "selection" and fdef.get("selection"):
                    for val, _label in fdef["selection"]:
                        action = _STATE_ACTION_MAP.get(val)
                        if action and action not in result[model]:
                            result[model].append(action)

    return result


def scan_access(client: OdooClient, model_names: list[str],
                max_workers: int = 10) -> dict[str, dict[str, bool]]:
    """Check CRUD access rights for each model."""
    result: dict[str, dict[str, bool]] = {}
    ops = ("read", "write", "create", "unlink")

    def _check(model: str) -> tuple[str, dict[str, bool]]:
        access = {}
        for op in ops:
            try:
                access[op] = bool(client.execute(
                    model, "check_access_rights", op, False,
                ))
            except Exception:
                access[op] = False
        return model, access

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check, m): m for m in model_names}
        for future in as_completed(futures):
            model, access = future.result()
            result[model] = access

    return result


def _default_cache_path() -> str:
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "openclaw-odoo", "schema_cache.json",
    )


def load_cache(cache_path: str | None = None) -> dict | None:
    """Load cached schema from disk. Returns None if missing/invalid."""
    path = cache_path or _default_cache_path()
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_cache(data: dict, cache_path: str | None = None) -> str:
    """Save schema cache to disk. Creates parent dirs if needed.

    Sets file permissions to 0600 (owner read/write only) because
    the cache may contain model metadata that should not be
    world-readable.
    """
    path = cache_path or _default_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.chmod(path, 0o600)
    return path


def full_discovery(client: OdooClient, cache_path: str | None = None) -> dict:
    """Run complete Level 3 discovery scan and save to cache.

    Returns the full schema dict.
    """
    start = time.monotonic()
    logger.info("Starting Odoo schema discovery...")

    # Step 1: Scan models
    models_raw = scan_models(client)
    model_names = list(models_raw.keys())
    logger.info("Found %d models", len(model_names))

    # Step 2: Scan fields (parallel)
    fields_by_model = scan_fields(client, model_names)

    # Step 3: Scan workflows
    workflows = scan_workflows(client, model_names, fields_by_model=fields_by_model)

    # Step 4: Scan access rights (parallel)
    access = scan_access(client, model_names)

    # Assemble cache
    elapsed = round(time.monotonic() - start, 1)
    cache = {
        "version": "1.0",
        "odoo_url": getattr(client, "base_url", ""),
        "database": getattr(client.config, "odoo_db", ""),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scan_duration_seconds": elapsed,
        "model_count": len(model_names),
        "models": {},
    }
    for model_name in model_names:
        info = models_raw[model_name]
        cache["models"][model_name] = {
            "label": info["label"],
            "module": info["module"],
            "description": info["description"],
            "access": access.get(model_name, {}),
            "fields": fields_by_model.get(model_name, {}),
            "workflows": workflows.get(model_name, []),
        }

    path = save_cache(cache, cache_path)
    logger.info("Discovery complete in %.1fs. Cache saved to %s", elapsed, path)
    return cache
