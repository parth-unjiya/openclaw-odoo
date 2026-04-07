"""OpenClaw skill interface -- thin JSON stdin/stdout bridge for AI agents."""
from __future__ import annotations

import json
import logging
import sys
import threading

from typing import Any

from ..client import OdooClient, _BLOCKED_METHODS, _WRITE_METHODS, _READ_METHODS
from ..config import load_config
from ..errors import sanitize_error as _sanitize_error
from ..batch import batch_execute
from ..modules import partners, sales, crm, inventory, accounting, hr, projects
from ..modules import purchase
from ..modules import calendar_mod
from ..intelligence.smart_actions import SmartActionHandler
from ..intelligence.analytics import (
    SalesAnalytics, FinancialAnalytics, InventoryAnalytics,
    HRAnalytics, PipelineAnalytics, full_business_dashboard,
)
from ..intelligence.file_import import import_csv, import_excel, export_records

logger = logging.getLogger("openclaw_odoo.skill")

# ── Dynamic model registry (lazy-initialized) ─────────────────
_registry_lock = threading.Lock()
_registry = None


def _get_registry(client: OdooClient):
    """Return a loaded ModelRegistry, creating it lazily on first call.

    Loads from the schema cache and generates auto-actions for all
    discovered custom models.  Uses double-checked locking so that
    concurrent callers don't race on initialisation.
    """
    global _registry
    if _registry is not None:
        return _registry

    with _registry_lock:
        if _registry is not None:
            return _registry

        try:
            from ..registry import ModelRegistry
            from ..auto_actions import (
                generate_crud_actions, generate_workflow_actions,
            )
            config = client.config
            reg = ModelRegistry(config)
            reg.load()
            if reg.all_models():
                actions: dict = {}
                for info in reg.custom_models():
                    actions.update(generate_crud_actions(client, info))
                    actions.update(generate_workflow_actions(client, info))
                reg.register_auto_actions(actions)
            _registry = reg
        except Exception:
            logger.debug("Registry init skipped (cache may not exist yet)")
            return None

    return _registry


def _pop(params: dict, key: str, default=None):
    return params.pop(key, default)


def _unpack_values(params: dict) -> dict:
    """Pop a nested ``values`` dict and merge its keys into *params*."""
    values = _pop(params, "values", None)
    if values:
        params.update(values)
    return params


# ── Dispatch registry ──────────────────────────────────────────
#
# Each entry maps an action name to a callable with the signature
#   (client: OdooClient, params: dict) -> Any
#
# Plain module functions use a simple lambda.  Actions that need
# pre-processing (values unpacking, class instantiation, inline
# logic) use small helper lambdas or are handled in the _SPECIAL
# dict further below.

_ACTION_MAP: dict[str, Any] = {
    # ── Partners ──
    "create_partner":       lambda c, p: partners.create_partner(c, **p),
    "find_partner":         lambda c, p: partners.find_partner(c, **p),
    "get_partner":          lambda c, p: partners.get_partner(c, **p),
    "update_partner":       lambda c, p: partners.update_partner(c, **_unpack_values(p)),
    "delete_partner":       lambda c, p: partners.delete_partner(c, **p),
    "get_partner_summary":  lambda c, p: partners.get_partner_summary(c, **p),
    "get_top_customers":    lambda c, p: partners.get_top_customers(c, **p),

    # ── Sales ──
    "create_quotation":     lambda c, p: sales.create_quotation(c, **p),
    "confirm_order":        lambda c, p: sales.confirm_order(c, **p),
    "send_quotation_email": lambda c, p: sales.send_quotation_email(c, **p),
    "cancel_order":         lambda c, p: sales.cancel_order(c, **p),
    "get_order":            lambda c, p: sales.get_order(c, **p),
    "search_orders":        lambda c, p: sales.search_orders(c, **p),
    "analyze_sales":        lambda c, p: sales.analyze_sales(c, **p),
    "get_sales_trend":      lambda c, p: sales.get_sales_trend(c, **p),

    # ── CRM ──
    "create_lead":          lambda c, p: crm.create_lead(c, **p),
    "create_opportunity":   lambda c, p: crm.create_opportunity(c, **p),
    "get_pipeline":         lambda c, p: crm.get_pipeline(c, **p),
    "move_stage":           lambda c, p: crm.move_stage(c, **p),
    "mark_won":             lambda c, p: crm.mark_won(c, **p),
    "mark_lost":            lambda c, p: crm.mark_lost(c, **p),
    "analyze_pipeline":     lambda c, p: crm.analyze_pipeline(c, **p),
    "get_forecast":         lambda c, p: crm.get_forecast(c, **p),

    # ── Inventory ──
    "create_product":       lambda c, p: inventory.create_product(c, **p),
    "search_products":      lambda c, p: inventory.search_products(c, **p),
    "check_availability":   lambda c, p: inventory.check_availability(c, **p),
    "get_stock_levels":     lambda c, p: inventory.get_stock_levels(c, **p),
    "get_low_stock":        lambda c, p: inventory.get_low_stock(c, **p),
    "get_stock_valuation":  lambda c, p: inventory.get_stock_valuation(c, **p),

    # ── Accounting ──
    "create_invoice":             lambda c, p: accounting.create_invoice(c, **p),
    "post_invoice":               lambda c, p: accounting.post_invoice(c, **p),
    "send_invoice_email":         lambda c, p: accounting.send_invoice_email(c, **p),
    "register_payment":           lambda c, p: accounting.register_payment(c, **p),
    "get_unpaid_invoices":        lambda c, p: accounting.get_unpaid_invoices(c, **p),
    "get_overdue_invoices":       lambda c, p: accounting.get_overdue_invoices(c, **p),
    "analyze_financial_ratios":   lambda c, p: accounting.analyze_financial_ratios(c, **p),
    "get_aging_report":           lambda c, p: accounting.get_aging_report(c, **p),

    # ── HR ──
    "create_employee":      lambda c, p: hr.create_employee(c, **p),
    "checkin":              lambda c, p: hr.checkin(c, **p),
    "checkout":             lambda c, p: hr.checkout(c, **p),
    "get_attendance":       lambda c, p: hr.get_attendance(c, **p),
    "request_leave":        lambda c, p: hr.request_leave(c, **p),
    "get_leaves":           lambda c, p: hr.get_leaves(c, **p),
    "get_headcount_summary": lambda c, p: hr.get_headcount_summary(c, **p),

    # ── Projects ──
    "create_project":       lambda c, p: projects.create_project(c, **p),
    "create_task":          lambda c, p: projects.create_task(c, **p),
    "update_task":          lambda c, p: projects.update_task(c, **_unpack_values(p)),
    "search_tasks":         lambda c, p: projects.search_tasks(c, **p),
    "log_timesheet":        lambda c, p: projects.log_timesheet(c, **p),
    "get_project_summary":  lambda c, p: projects.get_project_summary(c, **p),
    "create_ticket":        lambda c, p: projects.create_ticket(c, **p),

    # ── Purchase ──
    "create_purchase_order": lambda c, p: purchase.create_purchase_order(c, **p),
    "confirm_purchase":      lambda c, p: purchase.confirm_purchase(c, **p),
    "cancel_purchase":       lambda c, p: purchase.cancel_purchase(c, **p),
    "get_purchase":          lambda c, p: purchase.get_purchase(c, **p),
    "search_purchases":      lambda c, p: purchase.search_purchases(c, **p),
    "get_purchase_summary":  lambda c, p: purchase.get_purchase_summary(c, **p),

    # ── Calendar ──
    "create_event":         lambda c, p: calendar_mod.create_event(c, **p),
    "get_event":            lambda c, p: calendar_mod.get_event(c, **p),
    "search_events":        lambda c, p: calendar_mod.search_events(c, **p),
    "update_event":         lambda c, p: calendar_mod.update_event(c, **p),
    "delete_event":         lambda c, p: calendar_mod.delete_event(c, **p),
    "get_today_events":     lambda c, p: calendar_mod.get_today_events(c, **p),
    "get_upcoming_events":  lambda c, p: calendar_mod.get_upcoming_events(c, **p),

    # ── Import / Export ──
    "import_csv":           lambda c, p: import_csv(c, **p),
    "import_excel":         lambda c, p: import_excel(c, **p),
    "export_records":       lambda c, p: export_records(c, **p),
}


# ── Smart-action helpers (lazy SmartActionHandler instantiation) ──

def _smart_action(method_name: str):
    """Return a dispatcher that lazily creates a SmartActionHandler."""
    def _handler(client: OdooClient, params: dict) -> Any:
        smart = SmartActionHandler(client)
        return getattr(smart, method_name)(**params)
    return _handler


_SMART_ACTION_MAP: dict[str, Any] = {
    "smart_create_quotation": _smart_action("smart_create_quotation"),
    "smart_create_invoice":   _smart_action("smart_create_invoice"),
    "smart_create_lead":      _smart_action("smart_create_lead"),
    "smart_create_task":      _smart_action("smart_create_task"),
    "smart_create_employee":  _smart_action("smart_create_employee"),
    "smart_create_purchase":  _smart_action("smart_create_purchase"),
}


# ── Analytics dashboard helpers ──

_DASHBOARD_MAP: dict[str, Any] = {
    "sales_dashboard":     lambda c, p: SalesAnalytics(c).dashboard(),
    "financial_dashboard": lambda c, p: FinancialAnalytics(c).dashboard(),
    "inventory_dashboard": lambda c, p: InventoryAnalytics(c).dashboard(),
    "hr_dashboard":        lambda c, p: HRAnalytics(c).dashboard(),
    "pipeline_dashboard":  lambda c, p: PipelineAnalytics(c).dashboard(),
    "full_dashboard":      lambda c, p: full_business_dashboard(c),
}


# ── Generic CRUD handlers ──────────────────────────────────────

def _generic_search(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    return client.search_read(model, **params)


def _generic_create(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    values = _pop(params, "values", {})
    record_id = client.create(model, values)
    return {"id": record_id, "web_url": client.web_url(model, record_id)}


def _generic_update(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    record_id = _pop(params, "record_id")
    values = _pop(params, "values", {})
    client.write(model, [record_id], values)
    return {"success": True, "id": record_id}


def _generic_delete(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    record_id = _pop(params, "record_id")
    permanent = _pop(params, "permanent", False)
    if permanent:
        client.unlink(model, [record_id])
    else:
        client.write(model, [record_id], {"active": False})
    return {"success": True, "id": record_id}


def _generic_execute(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    method = _pop(params, "method")
    args = _pop(params, "args", [])
    kwargs = _pop(params, "kwargs", {})

    # Security: block dangerous methods
    if method in _BLOCKED_METHODS:
        raise PermissionError(
            f"Method '{method}' is blocked for security reasons"
        )

    # Respect readonly mode for write-like methods
    if method in _WRITE_METHODS:
        config = getattr(client, "config", None)
        if config is not None and getattr(config, "readonly", False) is True:
            raise PermissionError(
                f"Method '{method}' is not allowed in readonly mode"
            )

    return client.execute(model, method, *args, **kwargs)


def _generic_fields(client: OdooClient, params: dict) -> Any:
    model = _pop(params, "model")
    return client.fields_get(model)


def _generic_batch(client: OdooClient, params: dict) -> Any:
    operations = _pop(params, "operations", [])
    fail_fast = _pop(params, "fail_fast", True)
    return batch_execute(client, operations, fail_fast=fail_fast)


_GENERIC_MAP: dict[str, Any] = {
    "search":  _generic_search,
    "create":  _generic_create,
    "update":  _generic_update,
    "delete":  _generic_delete,
    "execute": _generic_execute,
    "fields":  _generic_fields,
    "batch":   _generic_batch,
}


# ── Public API ─────────────────────────────────────────────────

def route_action(client: OdooClient, action: str, params: dict) -> Any:
    try:
        return _dispatch(client, action, params)
    except Exception as e:
        logger.exception("Action '%s' failed", action)
        return {"error": True, "message": _sanitize_error(str(e)), "action": action}


def _dispatch(client: OdooClient, action: str, params: dict) -> Any:
    # Try each registry in priority order.
    handler = (
        _ACTION_MAP.get(action)
        or _SMART_ACTION_MAP.get(action)
        or _DASHBOARD_MAP.get(action)
    )
    if handler is not None:
        return handler(client, params)

    # Check auto-generated actions from model registry (between dashboards and generic)
    registry = _get_registry(client)
    if registry is not None:
        auto_actions = registry.get_auto_actions()
        auto_handler = auto_actions.get(action)
        if auto_handler is not None:
            return auto_handler(**params)

    handler = _GENERIC_MAP.get(action)
    if handler is not None:
        return handler(client, params)

    return {"error": True, "message": f"Unknown action: {action}", "action": action}


def main() -> None:
    config = load_config()
    with OdooClient(config) as client:
        raw = sys.stdin.read()
        try:
            request = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result = {"error": True, "message": "Invalid JSON input", "action": ""}
        else:
            action = request.get("action", "")
            params = request.get("params", {})
            result = route_action(client, action, params)
        json.dump(result, sys.stdout, default=str)
        sys.stdout.write("\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
