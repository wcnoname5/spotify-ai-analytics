"""The report LangGraph (drafter -> reviewer -> revise|end) and the
generate_report orchestration entry point the UI calls."""
from loguru import logger
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from .nodes import make_report_nodes
from .observability import get_langfuse_callbacks, get_trace_url
from .state import ReportResult, ReportState
from .tools import make_report_tools


def build_report_graph(tools: list):
    """Construct and compile the 2-node report StateGraph."""
    drafter_node, reviewer_node, route_after_review = make_report_nodes(tools)
    graph = StateGraph(ReportState)
    graph.add_node("drafter", drafter_node)
    graph.add_node("reviewer", reviewer_node)
    graph.set_entry_point("drafter")
    graph.add_edge("drafter", "reviewer")
    graph.add_conditional_edges(
        "reviewer", route_after_review, {"drafter": "drafter", "end": END}
    )
    logger.debug("build_report_graph: compiled report graph")
    return graph.compile()


def generate_report(
    *,
    style: str,
    start_date: str,
    end_date: str,
    db_path: str,
    model: BaseChatModel,
) -> ReportResult:
    """Run the report graph end-to-end and return a UI-friendly result.

    Args:
        style: One of "monthly_review", "roast", "gentle", "critic".
        start_date: ISO "YYYY-MM-DD" range start.
        end_date: ISO "YYYY-MM-DD" range end.
        db_path: Path to history.db.
        model: The chat model used by both the drafter and the reviewer.
    """
    logger.info("generate_report: style={} range={}..{}",
                style, start_date, end_date)
    tools = make_report_tools(db_path)
    graph = build_report_graph(tools)
    callbacks = get_langfuse_callbacks()
    config = {
        "configurable": {"model": model},
        "callbacks": callbacks,
    }
    initial: ReportState = {
        "style": style,
        "start_date": start_date,
        "end_date": end_date,
        "draft": "",
        "review_feedback": "",
        "revision_count": 0,
        "approved": False,
        "tool_log": [],
        "final_report": "",
    }
    final = graph.invoke(initial, config=config)
    trace_url = get_trace_url(callbacks)
    result = ReportResult(
        text=final["final_report"] or final["draft"],
        style=style,
        revision_count=final["revision_count"],
        approved=final["approved"],
        tool_log=final["tool_log"],
        trace_url=trace_url,
    )
    logger.info("generate_report: done — approved={} revisions={}",
                result.approved, result.revision_count)
    return result
