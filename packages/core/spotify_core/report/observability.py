"""Optional Langfuse tracing for the report graph.

get_langfuse_callbacks returns a LangChain callback list when all three
Langfuse env vars are present, and an empty list otherwise. get_trace_url is a
best-effort lookup of a finished run's trace URL. Both degrade silently when
Langfuse is not configured — the graph always runs.
"""
import os
from typing import Optional

from loguru import logger

_LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def _langfuse_configured() -> bool:
    return all(os.getenv(k) for k in _LANGFUSE_KEYS)


def get_langfuse_callbacks() -> list:
    """Return [CallbackHandler()] if Langfuse is fully configured, else []."""
    if not _langfuse_configured():
        logger.debug("get_langfuse_callbacks: Langfuse keys absent — tracing off")
        return []
    try:
        from langfuse.langchain import CallbackHandler
        logger.info("get_langfuse_callbacks: Langfuse tracing enabled")
        return [CallbackHandler()]
    except Exception:
        logger.exception("get_langfuse_callbacks: failed to init Langfuse")
        return []


def get_trace_url(callbacks: list) -> Optional[str]:
    """Best-effort: the Langfuse trace URL for the run that used these callbacks.

    Returns None when Langfuse is not configured, or whenever the trace id /
    URL cannot be resolved — tracing is optional and must never break a run.

    Args:
        callbacks: The list returned by get_langfuse_callbacks and threaded
            through the just-completed graph run.
    """
    if not callbacks:
        return None
    handler = callbacks[0]
    try:
        # The v3 CallbackHandler exposes the last run's trace id; the attribute
        # name has shifted across releases, so try both known forms.
        trace_id = getattr(handler, "last_trace_id", None)
        if trace_id is None and hasattr(handler, "get_trace_id"):
            trace_id = handler.get_trace_id()
        if not trace_id:
            logger.debug("get_trace_url: no trace id on the callback handler")
            return None
        from langfuse import get_client
        url = get_client().get_trace_url(trace_id=trace_id)
        logger.info("get_trace_url: resolved trace URL")
        return url
    except Exception:
        logger.exception("get_trace_url: failed to resolve trace URL")
        return None
