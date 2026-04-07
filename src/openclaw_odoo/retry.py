"""Exponential backoff retry decorator for transient errors."""
import time
import random
import functools
from typing import Callable
from .errors import OdooClawError


def with_retry(max_retries: int = 3, base_delay: float = 1.0,
               max_delay: float = 30.0, backoff_factor: float = 2.0):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OdooClawError as e:
                    if not getattr(e, 'retryable', False):
                        raise
                    if attempt == max_retries:
                        raise
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    delay *= random.uniform(0.5, 1.5)
                    time.sleep(delay)
            raise OdooClawError("Max retries exceeded")
        return wrapper
    return decorator
