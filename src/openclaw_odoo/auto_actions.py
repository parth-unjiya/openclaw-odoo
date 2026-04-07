"""Auto-generated CRUD, workflow, and analytics actions from registry."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from .client import OdooClient
from .errors import OdooRecordNotFoundError
from .fields import select_smart_fields
from .intelligence.smart_actions import SmartActionHandler
from .registry import ModelInfo

logger = logging.getLogger("openclaw_odoo.auto_actions")

_SAFE_WORKFLOW_PREFIXES = ("action_", "button_")
_SAFE_WORKFLOW_METHODS = frozenset({
    "mark_as_done", "set_draft", "post", "confirm", "cancel",
    "approve", "refuse", "send", "validate", "reset",
})


def _pluralize(word: str) -> str:
    """Simple English pluralization."""
    if word.endswith("s") or word.endswith("x") or word.endswith("sh") or word.endswith("ch"):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _action_names_for(label: str) -> dict[str, str]:
    """Generate action names from a model label.

    Args:
        label: Human-readable model label (e.g. "Fleet Vehicle").

    Returns:
        Dict mapping operation names to action name strings.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    slug_plural = "_".join(slug.split("_")[:-1] + [_pluralize(slug.split("_")[-1])])
    return {
        "search": f"search_{slug_plural}",
        "create": f"create_{slug}",
        "get": f"get_{slug}",
        "update": f"update_{slug}",
        "delete": f"delete_{slug}",
        "find": f"find_{slug}",
        "find_or_create": f"find_or_create_{slug}",
    }


def generate_crud_actions(client: OdooClient, info: ModelInfo) -> dict[str, Callable]:
    """Generate CRUD + find actions for a model. Skips builtins."""
    if info.is_builtin:
        return {}

    names = _action_names_for(info.label)
    actions: dict[str, Callable] = {}
    model = info.name
    name_field = info.name_field
    smart = SmartActionHandler(client)

    def _search(domain=None, fields=None, limit=None, offset=0, order=None, **kw):
        smart_fields = fields
        if not smart_fields:
            try:
                fdef = client.fields_get(model)
                smart_fields = select_smart_fields(fdef)
            except Exception:
                smart_fields = None
        return client.search_read(model, domain=domain or [], fields=smart_fields,
                                  limit=limit, offset=offset, order=order)

    def _create(values=None, **kw):
        vals = values or kw
        new_id = client.create(model, vals)
        return {"id": new_id, "web_url": client.web_url(model, new_id)}

    def _get(record_id=None, fields=None, **kw):
        rid = record_id or kw.get("id")
        records = client.search_read(model, domain=[["id", "=", int(rid)]], fields=fields)
        if not records:
            raise OdooRecordNotFoundError(
                f"{info.label} {rid} not found", model=model
            )
        return records[0]

    def _update(record_id=None, values=None, **kw):
        rid = record_id or kw.get("id")
        vals = values or {k: v for k, v in kw.items() if k != "id" and k != "record_id"}
        client.write(model, [int(rid)], vals)
        return {"id": int(rid), "web_url": client.web_url(model, int(rid))}

    def _delete(record_id=None, permanent=False, **kw):
        rid = int(record_id or kw.get("id"))
        if permanent:
            client.unlink(model, [rid])
            return {"id": rid, "deleted": True}
        client.write(model, [rid], {"active": False})
        return {"id": rid, "archived": True}

    def _find(name=None, query=None, **kw):
        q = name or query or ""
        return client.search_read(model, domain=[[name_field, "ilike", q]],
                                  limit=10)

    def _find_or_create(name=None, extra_values=None, **kw):
        q = name or ""
        return smart.generic_find_or_create(
            model=model, name=q,
            name_field=name_field,
            extra_values=extra_values,
        )

    actions[names["search"]] = _search
    actions[names["create"]] = _create
    actions[names["get"]] = _get
    actions[names["update"]] = _update
    actions[names["delete"]] = _delete
    actions[names["find"]] = _find
    actions[names["find_or_create"]] = _find_or_create

    return actions


def generate_workflow_actions(client: OdooClient, info: ModelInfo) -> dict[str, Callable]:
    """Generate workflow action handlers from discovered buttons."""
    if info.is_builtin or not info.workflows:
        return {}

    slug = re.sub(r"[^a-z0-9]+", "_", info.label.lower()).strip("_")
    actions: dict[str, Callable] = {}

    for method_name in info.workflows:
        # Security: only allow methods matching safe prefixes or known-safe set
        is_safe = (
            any(method_name.startswith(p) for p in _SAFE_WORKFLOW_PREFIXES)
            or method_name in _SAFE_WORKFLOW_METHODS
        )
        if not is_safe:
            logger.warning(
                "Skipping unsafe workflow method %r on model %s",
                method_name, info.name,
            )
            continue

        # Strip common prefixes for cleaner action names
        clean = method_name
        for prefix in ("action_", "button_"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        action_name = f"{clean}_{slug}"

        def _make_handler(m=method_name):
            def handler(record_id=None, **kw):
                rid = int(record_id or kw.get("id", 0))
                return client.execute(info.name, m, [rid])
            return handler

        actions[action_name] = _make_handler()

    return actions


def generate_auto_dashboard(client: OdooClient, info: ModelInfo,
                            date_from: str | None = None,
                            date_to: str | None = None) -> dict:
    """Generate a basic analytics dashboard for any model."""
    domain: list = []
    if date_from and info.date_fields:
        domain.append([info.date_fields[0], ">=", date_from])
    if date_to and info.date_fields:
        domain.append([info.date_fields[0], "<=", date_to])

    total = client.search_count(info.name, domain=domain)

    # Aggregate money fields via server-side read_group
    totals = {}
    if info.money_fields:
        group_result = client.execute(
            info.name, "read_group",
            domain, info.money_fields, [],  # empty groupby = single group
        )
        if group_result:
            for mf in info.money_fields:
                totals[mf] = group_result[0].get(mf, 0) or 0

    # Group by status via server-side read_group
    by_status: dict[str, int] = {}
    if info.status_field:
        status_groups = client.execute(
            info.name, "read_group",
            domain, [info.status_field], [info.status_field],
        )
        for group in status_groups:
            val = group.get(info.status_field, "unknown")
            count = group.get(f"{info.status_field}_count", 0)
            by_status[str(val)] = count

    # Recent records
    recent = client.search_read(
        info.name, domain=domain, limit=10,
        order="create_date desc",
    )

    return {
        "model": info.name,
        "label": info.label,
        "total_records": total,
        "by_status": by_status,
        "totals": totals,
        "recent": recent,
    }


def generate_import_signatures(registry) -> dict[frozenset, str]:
    """Build model signatures from registry for CSV auto-detection."""
    sigs = {}
    for info in registry.all_models():
        if info.is_builtin:
            continue
        labels = frozenset(
            f.label.lower() for f in info.fields.values()
            if f.type in ("char", "text", "many2one", "integer", "float", "monetary")
            and f.store and not f.name.startswith("_")
        )
        if len(labels) >= 3:
            sigs[labels] = info.name
    return sigs
