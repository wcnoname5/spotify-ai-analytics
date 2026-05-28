"""Optional Langfuse tracing for the report graph.

`langfuse_session` groups one report run into a Langfuse session;
`get_trace_url` is a best-effort lookup of a finished run's trace URL;
`update_trace_metadata` and `extract_usage` record per-call token usage on the active span. 
All degrade silently when Langfuse is not configured — the graph always runs.
"""
import os
import uuid
from contextlib import contextmanager
from typing import Optional

from loguru import logger

_LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def _langfuse_configured() -> bool:
    return all(os.getenv(k) for k in _LANGFUSE_KEYS)


@contextmanager
def langfuse_session(style: str = "", period_type: str = ""):
    """Context manager that groups one generate_report() run into a Langfuse session.

    Yields the callbacks list to pass into the graph config. A fresh UUID
    session_id is propagated via propagate_attributes so every child trace
    (drafter, reviewer, tool calls) shares the same session in the UI.
    Falls back to an empty list when Langfuse is not configured.
    """
    if not _langfuse_configured():
        logger.debug("langfuse_session: Langfuse not configured — skipping")
        yield []
        return
    try:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler
        session_id = str(uuid.uuid4())
        tags = ["spotify_report"]
        if style:
            tags.append(style)
        if period_type:
            tags.append(period_type)
        trace_name = f"report-{style}" if style else "spotify-report"
        logger.debug(
            "langfuse_session: session_id={} trace_name={} tags={}",
            session_id, trace_name, tags,
        )
        with propagate_attributes(session_id=session_id, tags=tags, trace_name=trace_name):
            yield [CallbackHandler()]
    except Exception:
        logger.exception("langfuse_session: failed to start session")
        yield []


def update_trace_metadata(metadata: dict) -> None:
    """Merge `metadata` into the currently-active Langfuse span; no-op if off.

    The LangChain CallbackHandler creates a span per graph node via OTEL
    context propagation, so calling `update_current_span` from inside the node
    attaches our post-hoc fields (e.g. OpenAI cached prompt tokens, only known
    after `.invoke()` returns) to that node's span.
    """
    if not metadata or not _langfuse_configured():
        return
    try:
        from langfuse import get_client
        get_client().update_current_span(metadata=metadata)
    except Exception:
        logger.exception("update_trace_metadata: failed to update span metadata")


def extract_usage(response) -> dict:
    """Pull the full token-usage dict off a LangChain AIMessage.

    Returns LangChain's standardized `usage_metadata` (input/output/total tokens
    plus `input_token_details.cache_read`, where langchain-openai surfaces
    OpenAI's cached prompt tokens). Falls back to the raw OpenAI
    `response_metadata.token_usage` block under a `raw` key, or {} when neither
    is populated.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return dict(usage)
    raw = (getattr(response, "response_metadata", None) or {}).get("token_usage")
    if raw:
        return {"raw": dict(raw)}
    return {}


def get_trace_url(callbacks: list) -> Optional[str]:
    """Best-effort: the Langfuse trace URL for the run that used these callbacks.

    Returns None when Langfuse is not configured, or whenever the trace id /
    URL cannot be resolved — tracing is optional and must never break a run.

    Args:
        callbacks: The list yielded by langfuse_session and threaded through
            the just-completed graph run.
    """
    if not callbacks:
        return None
    handler = callbacks[0]
    try:
        trace_id = getattr(handler, "last_trace_id", None)
        if not trace_id:
            logger.debug("get_trace_url: no trace id on the callback handler")
            return None
        from langfuse import get_client
        return get_client().get_trace_url(trace_id=trace_id)
    except Exception:
        logger.exception("get_trace_url: failed to resolve trace URL")
        return None
