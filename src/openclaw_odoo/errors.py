"""openclaw-odoo exception hierarchy with error classification."""


class OdooClawError(Exception):
    def __init__(self, message: str, model: str = "", method: str = ""):
        super().__init__(message)
        self.model = model
        self.method = method


class OdooConnectionError(OdooClawError):
    """Network, timeout, or protocol errors. Retryable."""
    retryable = True


class OdooAuthenticationError(OdooClawError):
    """Invalid credentials. Not retryable."""
    retryable = False


class OdooAccessError(OdooClawError):
    """Permission denied. Not retryable."""
    retryable = False


class OdooValidationError(OdooClawError):
    """Data constraint violation. Not retryable but may be auto-fixable."""
    retryable = False


class OdooRecordNotFoundError(OdooClawError):
    """Record does not exist. Not retryable."""
    retryable = False


_ERROR_PATTERNS = [
    ("AccessDenied", OdooAuthenticationError),
    ("AccessError", OdooAccessError),
    ("UserError", OdooValidationError),
    ("ValidationError", OdooValidationError),
    ("MissingError", OdooRecordNotFoundError),
    ("ConnectionError", OdooConnectionError),
    ("TimeoutError", OdooConnectionError),
    ("ConnectionRefusedError", OdooConnectionError),
]


def classify_error(fault_string: str, model: str = "", method: str = "") -> OdooClawError:
    for pattern, error_class in _ERROR_PATTERNS:
        if pattern in fault_string:
            return error_class(fault_string, model=model, method=method)
    return OdooClawError(fault_string, model=model, method=method)


# -- Error sanitization (shared by MCP + Skill interfaces) --

import re

_SANITIZE_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):.*", re.DOTALL),
    re.compile(r'File "[^"]*"[^\n]*\n'),
    re.compile(r"/[a-zA-Z0-9_/.-]+\.py:\d+"),
    re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\s+[^\n]{10,}", re.IGNORECASE),
]


def sanitize_error(msg: str) -> str:
    """Strip internal details (tracebacks, file paths, SQL) from error messages."""
    for pattern in _SANITIZE_PATTERNS:
        msg = pattern.sub("", msg)
    return msg.strip() or "An internal error occurred"
