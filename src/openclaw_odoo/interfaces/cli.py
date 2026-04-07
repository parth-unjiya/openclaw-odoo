"""CLI interface -- argparse-based command-line tool for openclaw-odoo."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..client import OdooClient
from ..config import load_config
from ..errors import OdooClawError
from ..modules.inventory import analyze_inventory_turnover
from ..modules.crm import analyze_pipeline
from ..modules.sales import analyze_sales


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openclaw-odoo",
        description="openclaw-odoo CLI -- Odoo 19 ERP operations from the command line.",
    )
    parser.add_argument("--config", help="Path to config JSON file")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search records")
    p_search.add_argument("model", help="Odoo model (e.g. res.partner)")
    p_search.add_argument("--domain", help="JSON domain filter")
    p_search.add_argument("--fields", help="Comma-separated field names")
    p_search.add_argument("--limit", type=int, help="Max records to return")

    # create
    p_create = sub.add_parser("create", help="Create a record")
    p_create.add_argument("model", help="Odoo model")
    p_create.add_argument("--values", required=True, help="JSON dict of field values")

    # update
    p_update = sub.add_parser("update", help="Update a record")
    p_update.add_argument("model", help="Odoo model")
    p_update.add_argument("record_id", type=int, help="Record ID to update")
    p_update.add_argument("--values", required=True, help="JSON dict of field values")

    # delete
    p_delete = sub.add_parser("delete", help="Delete (archive) a record")
    p_delete.add_argument("model", help="Odoo model")
    p_delete.add_argument("record_id", type=int, help="Record ID to delete")
    p_delete.add_argument("--permanent", action="store_true",
                          help="Permanently delete instead of archiving")

    # fields
    p_fields = sub.add_parser("fields", help="List model fields")
    p_fields.add_argument("model", help="Odoo model")

    # analytics
    p_analytics = sub.add_parser("analytics", help="Run analytics report")
    p_analytics.add_argument("report",
                             choices=["sales", "pipeline", "inventory"],
                             help="Report type")
    p_analytics.add_argument("--date-from", dest="date_from", help="Start date (YYYY-MM-DD)")
    p_analytics.add_argument("--date-to", dest="date_to", help="End date (YYYY-MM-DD)")

    # discover
    p_discover = sub.add_parser("discover", help="Discover Odoo models and cache schema")
    p_discover.add_argument("--refresh", action="store_true",
                            help="Force a fresh discovery scan (ignore cache)")
    p_discover.add_argument("--list", action="store_true", dest="list_models",
                            help="List all discovered models from cache")
    p_discover.add_argument("--model", help="Show details for a specific model")

    return parser


def run_command(args: argparse.Namespace, client: OdooClient) -> Any:
    cmd = args.command

    if cmd == "search":
        return _cmd_search(args, client)
    elif cmd == "create":
        return _cmd_create(args, client)
    elif cmd == "update":
        return _cmd_update(args, client)
    elif cmd == "delete":
        return _cmd_delete(args, client)
    elif cmd == "fields":
        return _cmd_fields(args, client)
    elif cmd == "analytics":
        return _cmd_analytics(args, client)
    elif cmd == "discover":
        return _cmd_discover(client, args)
    else:
        raise ValueError(f"Unknown command: {cmd}")


def _cmd_search(args: argparse.Namespace, client: OdooClient) -> list[dict]:
    kwargs: dict[str, Any] = {}
    try:
        kwargs["domain"] = json.loads(args.domain) if args.domain else []
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON in --domain argument"}))
        return []
    if args.fields:
        try:
            kwargs["fields"] = json.loads(args.fields)
        except json.JSONDecodeError:
            kwargs["fields"] = [f.strip() for f in args.fields.split(",")]
    if args.limit is not None:
        kwargs["limit"] = args.limit
    return client.search_read(args.model, **kwargs)


def _cmd_create(args: argparse.Namespace, client: OdooClient) -> dict:
    try:
        values = json.loads(args.values)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON in --values argument"}))
        return {}
    record_id = client.create(args.model, values)
    return {
        "id": record_id,
        "web_url": client.web_url(args.model, record_id),
    }


def _cmd_update(args: argparse.Namespace, client: OdooClient) -> dict:
    try:
        values = json.loads(args.values)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON in --values argument"}))
        return {}
    client.write(args.model, [args.record_id], values)
    return {"success": True, "id": args.record_id}


def _cmd_delete(args: argparse.Namespace, client: OdooClient) -> dict:
    if args.permanent:
        client.unlink(args.model, [args.record_id])
    else:
        client.write(args.model, [args.record_id], {"active": False})
    return {"success": True, "id": args.record_id}


def _cmd_fields(args: argparse.Namespace, client: OdooClient) -> dict:
    return client.fields_get(args.model)


def _cmd_analytics(args: argparse.Namespace, client: OdooClient) -> Any:
    if args.report == "sales":
        return analyze_sales(client, date_from=args.date_from, date_to=args.date_to)
    elif args.report == "pipeline":
        return analyze_pipeline(client)
    elif args.report == "inventory":
        return analyze_inventory_turnover(
            client, date_from=args.date_from, date_to=args.date_to,
        )
    else:
        raise ValueError(f"Unknown report: {args.report}")


def _cmd_discover(client: OdooClient, args: argparse.Namespace) -> Any:
    """Run model discovery or query the cached schema."""
    from ..registry import ModelRegistry
    from ..discovery import full_discovery

    registry = ModelRegistry(client.config)

    if args.refresh:
        cache = full_discovery(client)
        registry.load()
        return {
            "status": "discovery_complete",
            "model_count": cache.get("model_count", 0),
            "scan_duration_seconds": cache.get("scan_duration_seconds", 0),
        }

    # Load from cache
    registry.load()

    if args.model:
        info = registry.find(args.model)
        if not info:
            return {"error": f"Model not found: {args.model}"}
        return {
            "name": info.name,
            "label": info.label,
            "module": info.module,
            "name_field": info.name_field,
            "status_field": info.status_field,
            "money_fields": info.money_fields,
            "date_fields": info.date_fields,
            "workflows": info.workflows,
            "field_count": len(info.fields),
            "is_builtin": info.is_builtin,
        }

    if args.list_models:
        models = registry.all_models()
        return [
            {"name": m.name, "label": m.label, "module": m.module, "is_builtin": m.is_builtin}
            for m in models
        ]

    # Default: show summary
    all_m = registry.all_models()
    custom = registry.custom_models()
    return {
        "total_models": len(all_m),
        "custom_models": len(custom),
        "models_with_analytics": len(registry.models_with_analytics()),
        "models_with_workflows": len(registry.models_with_workflows()),
    }


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config if hasattr(args, "config") else None)
    client = OdooClient(config)
    try:
        result = run_command(args, client)
        print(json.dumps(result, indent=2, default=str))
    except OdooClawError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
    except Exception:
        print(json.dumps({"error": "An internal error occurred"}))
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
