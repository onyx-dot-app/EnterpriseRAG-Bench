"""Centralized Braintrust tracing utilities.

Provides idempotent initialization, span management, and trace flushing.
All functions are safe to call when tracing is not configured — they become no-ops.
"""

import atexit
import os
from contextlib import contextmanager
from typing import Any, Generator

BRAINTRUST_API_KEY = os.environ.get("BRAINTRUST_API_KEY")
BRAINTRUST_PROJECT = os.environ.get("BRAINTRUST_PROJECT")

_initialized = False


def is_tracing_enabled() -> bool:
    """Check if Braintrust tracing environment variables are configured."""
    return bool(BRAINTRUST_API_KEY and BRAINTRUST_PROJECT)


def init_tracing() -> None:
    """Initialize Braintrust tracing. Idempotent — safe to call multiple times."""
    global _initialized
    if _initialized or not is_tracing_enabled():
        return
    try:
        from braintrust import init_logger

        init_logger(project=BRAINTRUST_PROJECT)
        _initialized = True
        atexit.register(flush_traces)
    except Exception:
        pass


def flush_traces() -> None:
    """Flush all pending Braintrust trace data to the server."""
    if not _initialized:
        return
    try:
        from braintrust import flush

        flush()
    except Exception:
        pass


@contextmanager
def traced_span(name: str, span_type: str | None = None) -> Generator[Any, None, None]:
    """Context manager for a Braintrust span. No-op if tracing is not initialized."""
    if not _initialized:
        yield None
        return
    try:
        from braintrust import start_span

        kwargs: dict[str, Any] = {"name": name}
        if span_type:
            kwargs["type"] = span_type
        with start_span(**kwargs) as span:
            yield span
    except Exception:
        yield None


def log_to_span(span: Any, **kwargs: Any) -> None:
    """Log data to a Braintrust span. No-op if span is None."""
    if span is None:
        return
    try:
        span.log(**kwargs)
    except Exception:
        pass


def get_current_span() -> Any:
    """Get the current active Braintrust span, or None."""
    if not _initialized:
        return None
    try:
        from braintrust import current_span

        return current_span()
    except Exception:
        return None
