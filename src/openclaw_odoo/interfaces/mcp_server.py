"""MCP server interface -- exposes openclaw-odoo as a tool provider for AI assistants."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastmcp import FastMCP

from ..client import OdooClient, _BLOCKED_METHODS, _WRITE_METHODS, _READ_METHODS
from ..config import load_config
from ..errors import sanitize_error as _sanitize_error
from ..batch import batch_execute as _batch_execute
from ..intelligence.smart_actions import SmartActionHandler
from ..intelligence.analytics import (
    SalesAnalytics, FinancialAnalytics, InventoryAnalytics,
    HRAnalytics, PipelineAnalytics, full_business_dashboard,
)
from ..intelligence.file_import import (
    import_csv, import_excel, export_records,
)

logger = logging.getLogger("openclaw_odoo.mcp")


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def create_mcp_server(client: OdooClient) -> FastMCP:
    mcp = FastMCP("openclaw-odoo", instructions="Odoo 19 ERP connector")
    smart = SmartActionHandler(client)
    # Lazy-cached registry: _reg_cache[0] holds the ModelRegistry once loaded.
    # Using a list so inner functions can mutate the closure variable.
    _reg_cache: list = [None]
    _reg_attempted: list = [False]

    def _get_mcp_registry():
        """Return cached ModelRegistry, creating it lazily on first call."""
        if _reg_cache[0] is not None:
            return _reg_cache[0]
        if _reg_attempted[0]:
            return None
        _reg_attempted[0] = True
        try:
            from ..registry import ModelRegistry
            reg = ModelRegistry(client.config)
            reg.load()
            _reg_cache[0] = reg
            return reg
        except Exception:
            logger.debug("MCP: ModelRegistry init skipped (cache may not exist yet)")
            return None

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def search_records(
        model: str,
        domain: list | None = None,
        fields: list | None = None,
        limit: int = 50,
    ) -> str:
        """Search Odoo records. Returns matching records as JSON."""
        try:
            results = client.search_read(
                model, domain=domain or [], fields=fields or [], limit=limit,
            )
            return _json(results)
        except Exception as e:
            logger.exception("MCP tool search_records failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def count_records(
        model: str,
        domain: list | None = None,
    ) -> str:
        """Count records matching a domain filter. Returns an integer count."""
        try:
            count = client.search_count(model, domain=domain or [])
            return _json({"model": model, "count": count})
        except Exception as e:
            logger.exception("MCP tool count_records failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def create_record(model: str, values: dict) -> str:
        """Create a new record in the given Odoo model."""
        try:
            record_id = client.create(model, values)
            return _json({
                "id": record_id,
                "web_url": client.web_url(model, record_id),
            })
        except Exception as e:
            logger.exception("MCP tool create_record failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def update_record(model: str, record_id: int, values: dict) -> str:
        """Update an existing Odoo record by ID."""
        try:
            client.write(model, [record_id], values)
            return _json({"success": True, "id": record_id})
        except Exception as e:
            logger.exception("MCP tool update_record failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def delete_record(model: str, record_id: int, permanent: bool = False) -> str:
        """Delete an Odoo record by ID. Archives by default, permanently deletes if permanent=True."""
        try:
            if permanent:
                client.unlink(model, [record_id])
            else:
                client.write(model, [record_id], {"active": False})
            return _json({"success": True, "id": record_id, "permanent": permanent})
        except Exception as e:
            logger.exception("MCP tool delete_record failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def execute_method(
        model: str,
        method: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> str:
        """Execute an arbitrary method on an Odoo model."""
        try:
            # Block dangerous methods at the MCP interface level
            _MCP_EXTRA_BLOCKED = {"unlink"}  # use delete_record tool instead
            if method in _BLOCKED_METHODS or method in _MCP_EXTRA_BLOCKED:
                return _json({"error": f"Method '{method}' is blocked for safety reasons. Use the appropriate tool instead."})
            if client.config.readonly and method in _WRITE_METHODS:
                return _json({"error": f"Method '{method}' is not allowed in readonly mode"})
            result = client.execute(model, method, *(args or []), **(kwargs or {}))
            return _json(result)
        except Exception as e:
            logger.exception("MCP tool execute_method failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def batch_execute(
        operations: list[dict],
        fail_fast: bool = True,
    ) -> str:
        """Execute multiple Odoo operations in sequence. Each operation is {model, method, args, kwargs}."""
        try:
            result = _batch_execute(client, operations, fail_fast=fail_fast)
            return _json(result)
        except Exception as e:
            logger.exception("MCP tool batch_execute failed")
            return _json({"error": _sanitize_error(str(e))})

    _SMART_ACTIONS = {
        "find_or_create_partner", "find_or_create_product", "find_or_create_project",
        "resolve_department", "resolve_user",
        "smart_create_quotation", "smart_create_invoice", "smart_create_lead",
        "smart_create_task", "smart_create_employee", "smart_create_purchase",
    }

    @mcp.tool()
    def smart_action(action: str, params: dict | None = None) -> str:
        """Run a smart action by name (e.g. find_or_create_partner, smart_create_quotation)."""
        try:
            if action not in _SMART_ACTIONS:
                return _json({"error": f"Unknown action: {action}. Allowed: {sorted(_SMART_ACTIONS)}"})
            func = getattr(smart, action)
            params = params or {}
            result = func(**params)
            return _json(result)
        except Exception as e:
            logger.exception("MCP tool smart_action failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def analyze(report_type: str, params: dict | None = None) -> str:
        """Run an analytics dashboard. Types: sales, financial, inventory, hr, pipeline, full, auto."""
        try:
            params = params or {}
            dashboards = {
                "sales": lambda: SalesAnalytics(client).dashboard(**params),
                "financial": lambda: FinancialAnalytics(client).dashboard(),
                "inventory": lambda: InventoryAnalytics(client).dashboard(),
                "hr": lambda: HRAnalytics(client).dashboard(),
                "pipeline": lambda: PipelineAnalytics(client).dashboard(),
                "full": lambda: full_business_dashboard(client),
            }
            if report_type == "auto":
                model_name = params.get("model")
                if not model_name:
                    return _json({"error": "auto report requires 'model' in params"})
                try:
                    from ..auto_actions import generate_auto_dashboard
                    registry = _get_mcp_registry()
                    if registry is None:
                        return _json({"error": "ModelRegistry not available (schema cache missing?)"})
                    info = registry.resolve(model_name)
                    result = generate_auto_dashboard(
                        client, info,
                        date_from=params.get("date_from"),
                        date_to=params.get("date_to"),
                    )
                    return _json(result)
                except Exception as e:
                    logger.exception("MCP tool analyze (auto) failed")
                    return _json({"error": _sanitize_error(str(e))})
            fn = dashboards.get(report_type)
            if fn is None:
                return _json({"error": f"Unknown report type: {report_type}"})
            return _json(fn())
        except Exception as e:
            logger.exception("MCP tool analyze failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def import_file(
        filepath: str,
        model: str | None = None,
        column_map: dict | None = None,
        dry_run: bool = False,
    ) -> str:
        """Import records from a CSV or Excel file into Odoo."""
        try:
            if filepath.endswith((".xlsx", ".xls")):
                result = import_excel(
                    client, filepath, model=model,
                    column_map=column_map, dry_run=dry_run,
                )
            else:
                result = import_csv(
                    client, filepath, model=model,
                    column_map=column_map, dry_run=dry_run,
                )
            return _json(result)
        except Exception as e:
            logger.exception("MCP tool import_file failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def export_data(
        model: str,
        domain: list | None = None,
        fields: list | None = None,
        output_format: str = "csv",
    ) -> str:
        """Export Odoo records to a CSV or Excel file."""
        try:
            filepath = export_records(
                client, model, domain=domain or [],
                fields=fields or [], output_format=output_format,
            )
            return _json({"filepath": filepath})
        except Exception as e:
            logger.exception("MCP tool export_data failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def list_models() -> str:
        """List available Odoo models."""
        try:
            models = client.search_read(
                "ir.model",
                domain=[],
                fields=["model", "name"],
                limit=0,
            )
            return _json(models)
        except Exception as e:
            logger.exception("MCP tool list_models failed")
            return _json({"error": _sanitize_error(str(e))})

    @mcp.tool()
    def get_fields(model: str) -> str:
        """Get field definitions for an Odoo model."""
        try:
            return _json(client.fields_get(model))
        except Exception as e:
            logger.exception("MCP tool get_fields failed")
            return _json({"error": _sanitize_error(str(e))})

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("odoo://models")
    def resource_models() -> str:
        """List of available Odoo models."""
        models = client.search_read(
            "ir.model", domain=[], fields=["model", "name"], limit=0,
        )
        return _json(models)

    @mcp.resource("odoo://schema/{model}")
    def resource_schema(model: str) -> str:
        """Field schema for a given Odoo model."""
        return _json(client.fields_get(model))

    @mcp.resource("odoo://server/info")
    def resource_server_info() -> str:
        """Server connection info."""
        return _json({
            "url": client.config.odoo_url,
            "database": client.config.odoo_db,
            "connected": True,
        })

    return mcp


def main():
    """Entry point: create config, client, and run MCP server."""
    config = load_config()
    with OdooClient(config) as client:
        mcp = create_mcp_server(client)
        mcp.run()


if __name__ == "__main__":
    main()
