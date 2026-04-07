"""Batch execute with fail-fast support."""
from typing import Any

from .errors import OdooClawError


def batch_execute(client, operations: list[dict],
                  fail_fast: bool = True) -> dict[str, Any]:
    """Execute a list of Odoo operations sequentially.

    Each operation is a dict with 'model', 'method', optional 'args' and 'kwargs'.

    Args:
        client: OdooClient instance.
        operations: List of operation dicts to execute.
        fail_fast: If True, stop on first error (default True).

    Returns:
        Dict with success, total, succeeded, failed, and results list.
    """
    results = []
    succeeded = 0
    failed = 0

    for i, op in enumerate(operations):
        model = op["model"]
        method = op["method"]
        args = op.get("args", [])
        kwargs = op.get("kwargs", {})

        # Readonly enforcement is now centralized in client.execute()
        # which blocks all non-read methods when readonly=True.

        try:
            result = client.execute(model, method, *args, **kwargs)
            results.append({"index": i, "success": True, "result": result})
            succeeded += 1
        except OdooClawError as e:
            results.append({"index": i, "success": False, "error": str(e)})
            failed += 1
            if fail_fast:
                break

    return {
        "success": failed == 0,
        "total": len(operations),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
