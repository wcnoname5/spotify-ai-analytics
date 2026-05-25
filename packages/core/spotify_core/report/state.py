"""State types and helpers for the report graph.

Pure module — no LangGraph/LLM-runtime imports. The graph nodes import these
types; keeping them here lets tests construct and assert on state directly.
"""
from dataclasses import dataclass, field
from typing import Optional, TypedDict

from loguru import logger
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import BaseModel, Field

_RESULT_TRUNCATE = 500


@dataclass
class ToolCallRecord:
    """One tool call the drafter made — a projection of an AIMessage/ToolMessage pair."""
    name: str
    args: dict
    result: str
    success: bool
    error: Optional[str] = None


class ReviewVerdict(BaseModel):
    """Structured output of the reviewer node."""
    approved: bool = Field(description="True if the draft is good enough to ship.")
    feedback: str = Field(
        default="",
        description="Concrete, actionable revision notes. Empty when approved.",
    )


class ReportState(TypedDict):
    """Mutable state threaded through the report graph."""
    style: str
    period_type: str  # "weekly" | "monthly" | "custom"
    start_date: str
    end_date: str
    draft: str
    review_feedback: str
    revision_count: int
    approved: bool
    tool_log: list[ToolCallRecord]
    final_report: str


@dataclass
class ReportResult:
    """UI-facing result returned by generate_report."""
    text: str
    style: str
    revision_count: int
    approved: bool
    tool_log: list[ToolCallRecord] = field(default_factory=list)
    trace_url: Optional[str] = None


def extract_tool_log(messages: list[BaseMessage]) -> list[ToolCallRecord]:
    """Derive a ToolCallRecord list from a drafter conversation.

    Walks the message list once: every AIMessage.tool_calls entry is matched to
    its ToolMessage by tool_call_id. The messages list is the single source of
    truth; this is a read-only projection.
    """
    logger.debug("extract_tool_log: scanning {} messages", len(messages))
    pending: dict[str, tuple[str, dict]] = {}
    records: list[ToolCallRecord] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                pending[tc["id"]] = (tc["name"], tc.get("args", {}))
        if isinstance(msg, ToolMessage):
            name, args = pending.get(msg.tool_call_id, (msg.name or "unknown", {}))
            success = getattr(msg, "status", "success") != "error"
            content = str(msg.content)
            records.append(ToolCallRecord(
                name=name,
                args=args,
                result=content[:_RESULT_TRUNCATE],
                success=success,
                error=None if success else content,
            ))
    logger.info("extract_tool_log: derived {} tool-call records", len(records))
    return records
