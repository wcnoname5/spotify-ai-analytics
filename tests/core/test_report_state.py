"""Tests for spotify_core.report.state — state types and extract_tool_log."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from spotify_core.report.state import ToolCallRecord, extract_tool_log


def _ai_with_call(call_id, name, args):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def test_extract_tool_log_pairs_calls_and_results():
    messages = [
        HumanMessage(content="hi"),
        _ai_with_call("c1", "get_top_artists", {"start_date": "2024-01-01"}),
        ToolMessage(
            content="[{'artist': 'A'}]", tool_call_id="c1",
            name="get_top_artists", status="success",
        ),
        AIMessage(content="final draft"),
    ]
    log = extract_tool_log(messages)
    assert len(log) == 1
    assert isinstance(log[0], ToolCallRecord)
    assert log[0].name == "get_top_artists"
    assert log[0].args == {"start_date": "2024-01-01"}
    assert log[0].success is True
    assert log[0].error is None


def test_extract_tool_log_marks_errors():
    messages = [
        _ai_with_call("c1", "get_top_tracks", {}),
        ToolMessage(
            content="boom", tool_call_id="c1",
            name="get_top_tracks", status="error",
        ),
    ]
    log = extract_tool_log(messages)
    assert log[0].success is False
    assert log[0].error == "boom"


def test_extract_tool_log_empty_when_no_tool_calls():
    assert extract_tool_log([AIMessage(content="just a draft")]) == []
