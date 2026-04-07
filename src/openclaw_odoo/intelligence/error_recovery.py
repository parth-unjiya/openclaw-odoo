"""Error recovery with auto-fix strategies for common Odoo errors."""
import copy
import logging
import re
from datetime import datetime
from typing import Any, Optional

from ..errors import (
    OdooAccessError,
    OdooAuthenticationError,
    OdooClawError,
    OdooValidationError,
)

logger = logging.getLogger("openclaw_odoo.error_recovery")

_FIELD_NAME_RE = re.compile(r"field '(\w+)'")

_TYPE_DEFAULTS = {
    "char": "",
    "text": "",
    "boolean": False,
    "integer": 0,
    "float": 0.0,
    "monetary": 0.0,
    "date": False,
    "datetime": False,
    "selection": False,
    "many2one": False,
    "html": "",
}

_DATE_FORMATS = [
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
]


class ErrorRecovery:
    """Auto-fix handler that classifies Odoo errors and applies recovery strategies."""

    def __init__(self, client):
        self.client = client

    def _parse_field_name(self, error: OdooClawError) -> Optional[str]:
        match = _FIELD_NAME_RE.search(str(error))
        return match.group(1) if match else None

    def _fix_missing_required(self, operation: dict, error: OdooClawError) -> Optional[dict]:
        field_name = self._parse_field_name(error)
        if not field_name:
            return None
        fields_info = self.client.fields_get(operation["model"])
        if field_name not in fields_info:
            return None
        field_type = fields_info[field_name].get("type", "char")
        default_value = _TYPE_DEFAULTS.get(field_type, False)
        op = copy.deepcopy(operation)
        op["args"][0][field_name] = default_value
        return op

    def _fix_type_mismatch(self, operation: dict, error: OdooClawError) -> Optional[dict]:
        field_name = self._parse_field_name(error)
        if not field_name:
            return None
        fields_info = self.client.fields_get(operation["model"])
        if field_name not in fields_info:
            return None
        field_type = fields_info[field_name].get("type", "char")
        op = copy.deepcopy(operation)
        current_val = op["args"][0].get(field_name)
        try:
            if field_type == "float" or field_type == "monetary":
                op["args"][0][field_name] = float(current_val)
            elif field_type == "integer":
                op["args"][0][field_name] = int(current_val)
            elif field_type == "boolean":
                op["args"][0][field_name] = str(current_val).lower() in ("true", "1", "yes")
            elif field_type == "char" or field_type == "text":
                op["args"][0][field_name] = str(current_val)
            else:
                return None
        except (ValueError, TypeError):
            return None
        return op

    def _fix_duplicate(self, operation: dict, error: OdooClawError) -> Optional[dict]:
        values = operation["args"][0] if operation["args"] else {}
        domain = [[k, "=", v] for k, v in values.items() if isinstance(v, (str, int, float, bool))]
        if not domain:
            return None
        records = self.client.search_read(operation["model"], domain, limit=1)
        if records:
            return {"existing_record": records[0]}
        return None

    def _fix_field_not_found(self, operation: dict, error: OdooClawError) -> Optional[dict]:
        field_name = self._parse_field_name(error)
        if not field_name:
            return None
        op = copy.deepcopy(operation)
        if field_name in op["args"][0]:
            del op["args"][0][field_name]
            return op
        return None

    def _fix_date_format(self, operation: dict, error: OdooClawError) -> Optional[dict]:
        field_name = self._parse_field_name(error)
        if not field_name:
            return None
        op = copy.deepcopy(operation)
        raw_value = op["args"][0].get(field_name)
        if not raw_value or not isinstance(raw_value, str):
            return None
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw_value, fmt)
                op["args"][0][field_name] = parsed.strftime("%Y-%m-%d")
                return op
            except ValueError:
                continue
        return None

    def _fix_access_denied(self, operation: dict, error: OdooClawError) -> None:
        logger.warning(
            "Access denied for %s.%s -- cannot auto-fix. "
            "Check user permissions or API key scope.",
            operation.get("model"), operation.get("method"),
        )
        return None

    _STRATEGY_MAP = {
        "missing_required": "_fix_missing_required",
        "type_mismatch": "_fix_type_mismatch",
        "duplicate": "_fix_duplicate",
        "field_not_found": "_fix_field_not_found",
        "date_format": "_fix_date_format",
        "access_denied": "_fix_access_denied",
    }

    def _classify_for_recovery(self, error: OdooClawError) -> Optional[str]:
        msg = str(error).lower()
        if isinstance(error, (OdooAccessError, OdooAuthenticationError)):
            return "access_denied"
        if "required" in msg:
            return "missing_required"
        if "duplicate" in msg or "unique constraint" in msg:
            return "duplicate"
        if "does not exist" in msg and "field" in msg:
            return "field_not_found"
        if "expected" in msg and ("float" in msg or "integer" in msg or "boolean" in msg):
            return "type_mismatch"
        if "date format" in msg or ("date" in msg and "invalid" in msg):
            return "date_format"
        return None

    def recover(self, operation: dict, error: OdooClawError, max_attempts: int = 3) -> dict:
        """Attempt to auto-fix a failed operation and retry.

        Args:
            operation: Dict with 'model', 'method', 'args', 'kwargs'.
            error: The original OdooClawError that occurred.
            max_attempts: Maximum fix-and-retry cycles.

        Returns:
            Dict with success, result, attempts, and fixes_applied.
        """
        fixes_applied: list[str] = []
        current_op = copy.deepcopy(operation)
        current_error = error

        for attempt in range(1, max_attempts + 1):
            category = self._classify_for_recovery(current_error)
            if not category:
                return {"success": False, "result": None, "attempts": attempt, "fixes_applied": fixes_applied}

            strategy_name = self._STRATEGY_MAP.get(category)
            if not strategy_name:
                return {"success": False, "result": None, "attempts": attempt, "fixes_applied": fixes_applied}

            strategy = getattr(self, strategy_name)
            fix_result = strategy(current_op, current_error)

            if fix_result is None:
                return {"success": False, "result": None, "attempts": attempt, "fixes_applied": fixes_applied}

            # Duplicate fix returns the existing record directly
            if isinstance(fix_result, dict) and "existing_record" in fix_result:
                fixes_applied.append(category)
                return {"success": True, "result": fix_result, "attempts": attempt, "fixes_applied": fixes_applied}

            fixes_applied.append(category)
            current_op = fix_result

            try:
                result = self.client.execute(
                    current_op["model"], current_op["method"],
                    *current_op["args"], **current_op["kwargs"],
                )
                return {"success": True, "result": result, "attempts": attempt, "fixes_applied": fixes_applied}
            except OdooClawError as retry_error:
                current_error = retry_error
                continue

        return {"success": False, "result": None, "attempts": max_attempts, "fixes_applied": fixes_applied}
