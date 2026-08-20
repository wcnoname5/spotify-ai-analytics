"""Optional Langfuse tracing for the report agent.
"""
import uuid
from contextlib import contextmanager

from loguru import logger


@contextmanager
def langfuse_session(style: str = "", period_type: str = ""):
    """Group one report run into a Langfuse session; yield the callbacks list.

    A fresh UUID session_id is propagated to all childrens via `propagate_attributes`.
     Yields [] when Langfuse is off.
    """
    from spotify_core.config import settings

    if not settings.langfuse_configured:
        # silently skip tracing if no key configured
        yield []
        return
    try:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler

        session_id = str(uuid.uuid4())
        tags = ["spotify_report", *(t for t in (style, period_type) if t)]
        trace_name = f"report-{style}" if style else "spotify-report"
        with propagate_attributes(session_id=session_id, tags=tags, trace_name=trace_name):
            yield [CallbackHandler()]
    except Exception:
        logger.exception("langfuse_session: failed to start session")
        yield []
