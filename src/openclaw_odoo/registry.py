"""Model Registry -- merges discovery cache + user hints into a unified catalog."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("openclaw_odoo.registry")


@dataclass
class FieldInfo:
    """Schema information for a single Odoo model field."""
    name: str
    type: str
    label: str
    required: bool = False
    readonly: bool = False
    relation: str | None = None
    selection: list | None = None
    store: bool = True


@dataclass
class ModelInfo:
    """Schema information for a single Odoo model."""
    name: str
    label: str
    description: str = ""
    module: str = ""
    name_field: str = "name"
    aliases: list[str] = field(default_factory=list)
    fields: dict[str, FieldInfo] = field(default_factory=dict)
    important_fields: list[str] = field(default_factory=list)
    money_fields: list[str] = field(default_factory=list)
    date_fields: list[str] = field(default_factory=list)
    status_field: str | None = None
    workflows: list[str] = field(default_factory=list)
    access: dict[str, bool] = field(default_factory=dict)
    analytics_config: dict | None = None
    is_builtin: bool = False


# Models with hardcoded specialized logic in modules/
_BUILTIN_MODELS = frozenset({
    "res.partner", "sale.order", "crm.lead", "product.product",
    "account.move", "hr.employee", "project.task", "project.project",
    "purchase.order", "calendar.event", "stock.quant",
    "sale.order.line", "purchase.order.line", "account.move.line",
    "helpdesk.ticket", "hr.attendance", "hr.leave", "hr.expense",
    "account.analytic.line",
})

# Heuristic patterns for auto-inferring money fields
_MONEY_PATTERNS = re.compile(
    r"(cost|price|amount|total|revenue|fee|charge|salary|wage)", re.I
)


class ModelRegistry:
    """Unified catalog of all Odoo models: builtin + custom.

    Loads from a discovery cache file, merges user hints from config,
    and auto-infers field semantics (money, date, status, name).
    """

    def __init__(self, config):
        self._models: dict[str, ModelInfo] = {}
        self._alias_map: dict[str, str] = {}
        self._auto_actions: dict[str, Callable] = {}
        self._config = config

    def load(self, cache_path: str | None = None) -> None:
        """Load from schema_cache.json + merge model_hints from config."""
        from .discovery import load_cache, _default_cache_path

        self._models.clear()
        self._alias_map.clear()
        self._auto_actions.clear()

        cache = load_cache(cache_path or _default_cache_path())
        if not cache:
            return

        # Validate cache matches current config
        if (cache.get("odoo_url", "") != getattr(self._config, "odoo_url", "")
                or cache.get("database", "") != getattr(self._config, "odoo_db", "")):
            logger.warning("Cache URL/DB mismatch, ignoring stale cache")
            return

        hints = getattr(self._config, "model_hints", {}) or {}

        for model_name, raw in cache.get("models", {}).items():
            hint = hints.get(model_name, {})
            fields = self._build_fields(raw.get("fields", {}))
            info = self._build_model_info(model_name, raw, hint, fields)
            self._models[model_name] = info
            self._register_aliases(info)

    def discover(self, client, cache_path: str | None = None) -> None:
        """Run full discovery, save cache, then load."""
        from .discovery import full_discovery
        full_discovery(client, cache_path=cache_path)
        self.load(cache_path)

    # --- Lookups ---

    def get(self, model_name: str) -> ModelInfo | None:
        """Get a model by exact technical name. Returns None if not found."""
        return self._models.get(model_name)

    def find(self, query: str) -> ModelInfo | None:
        """Fuzzy lookup: exact name -> alias -> label substring."""
        if query in self._models:
            return self._models[query]
        if query in self._alias_map:
            return self._models.get(self._alias_map[query])
        query_lower = query.lower()
        if query_lower in self._alias_map:
            return self._models.get(self._alias_map[query_lower])
        for info in self._models.values():
            if query_lower in info.label.lower():
                return info
        return None

    def resolve(self, query: str) -> ModelInfo:
        """Like find(), but raises OdooClawError if not found."""
        info = self.find(query)
        if not info:
            from .errors import OdooClawError
            raise OdooClawError(f"Model not found: {query}")
        return info

    # --- Queries ---

    def all_models(self) -> list[ModelInfo]:
        """Return all registered models."""
        return list(self._models.values())

    def custom_models(self) -> list[ModelInfo]:
        """Return only non-builtin (custom) models."""
        return [m for m in self._models.values() if not m.is_builtin]

    def models_with_analytics(self) -> list[ModelInfo]:
        """Return models that have money or date fields (analytics-capable)."""
        return [m for m in self._models.values() if m.money_fields or m.date_fields]

    def models_with_workflows(self) -> list[ModelInfo]:
        """Return models that have workflow actions."""
        return [m for m in self._models.values() if m.workflows]

    def get_auto_actions(self) -> dict[str, Callable]:
        """Return a copy of registered auto-generated actions."""
        return dict(self._auto_actions)

    def register_auto_actions(self, actions: dict[str, Callable]) -> None:
        """Register auto-generated action handlers."""
        self._auto_actions.update(actions)

    # --- Internal ---

    def _build_fields(self, raw_fields: dict) -> dict[str, FieldInfo]:
        """Convert raw cache field dicts to FieldInfo dataclasses."""
        result = {}
        for fname, fdef in raw_fields.items():
            result[fname] = FieldInfo(
                name=fname,
                type=fdef.get("type", ""),
                label=fdef.get("string", fname),
                required=fdef.get("required", False),
                readonly=fdef.get("readonly", False),
                relation=fdef.get("relation"),
                selection=fdef.get("selection"),
                store=fdef.get("store", True),
            )
        return result

    def _build_model_info(self, name: str, raw: dict, hint: dict,
                          fields: dict[str, FieldInfo]) -> ModelInfo:
        """Assemble a ModelInfo from cache data + user hints + auto-inference."""
        # Auto-infer money, date, status fields
        money = hint.get("money_fields") or self._infer_money_fields(fields)
        dates = hint.get("date_fields") or self._infer_date_fields(fields)
        status = self._infer_status_field(fields)

        # Name field: hint > first required char field > "name"
        name_field = hint.get("name_field") or self._infer_name_field(fields)

        return ModelInfo(
            name=name,
            label=hint.get("label") or raw.get("label", name),
            description=hint.get("description") or raw.get("description", ""),
            module=raw.get("module", ""),
            name_field=name_field,
            aliases=hint.get("aliases", []),
            fields=fields,
            important_fields=hint.get("important_fields", []),
            money_fields=money,
            date_fields=dates,
            status_field=status,
            workflows=raw.get("workflows", []),
            access=raw.get("access", {}),
            analytics_config=hint.get("analytics"),
            is_builtin=name in _BUILTIN_MODELS,
        )

    def _register_aliases(self, info: ModelInfo) -> None:
        """Register user-defined and auto-inferred aliases for a model."""
        # User-defined aliases (highest priority)
        for alias in info.aliases:
            a = alias.lower()
            if a in self._alias_map:
                logger.warning(
                    "Alias collision: '%s' already maps to %s, skipping %s",
                    a, self._alias_map[a], info.name,
                )
            else:
                self._alias_map[a] = info.name

        # Auto-inferred alias from label (lowest priority)
        if info.label and not info.is_builtin:
            auto_alias = info.label.lower().replace(" ", "_")
            if auto_alias not in self._alias_map:
                self._alias_map[auto_alias] = info.name

    @staticmethod
    def _infer_money_fields(fields: dict[str, FieldInfo]) -> list[str]:
        """Infer money fields: monetary type + float with cost/price/amount pattern."""
        result = []
        for f in fields.values():
            if f.type == "monetary":
                result.append(f.name)
            elif f.type == "float" and _MONEY_PATTERNS.search(f.name):
                result.append(f.name)
        return result

    @staticmethod
    def _infer_date_fields(fields: dict[str, FieldInfo]) -> list[str]:
        """Infer date fields: any stored date or datetime field."""
        return [f.name for f in fields.values()
                if f.type in ("date", "datetime") and f.store]

    @staticmethod
    def _infer_status_field(fields: dict[str, FieldInfo]) -> str | None:
        """Infer the primary status field from common field names."""
        for name in ("state", "status", "x_status", "x_state", "stage"):
            if name in fields and fields[name].type == "selection":
                return name
        return None

    @staticmethod
    def _infer_name_field(fields: dict[str, FieldInfo]) -> str:
        """Infer the name/display field: first required char field, else 'name'."""
        for f in fields.values():
            if f.type == "char" and f.required and f.name != "id":
                return f.name
        return "name"
