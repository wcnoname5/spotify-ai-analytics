"""Tests for spotify_core.report.observability and prompts."""
from spotify_core.report.observability import get_langfuse_callbacks, get_trace_url
from spotify_core.report.prompts import REVIEWER_RUBRIC, STYLE_TEMPLATES


def test_langfuse_callbacks_empty_without_keys(monkeypatch):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert get_langfuse_callbacks() == []


def test_get_trace_url_none_without_callbacks():
    assert get_trace_url([]) is None


def test_style_templates_include_required_styles():
    # listening_review and roast are the must-have styles; the set may grow or
    # shrink, so this asserts a subset rather than an exact match.
    assert {"listening_review", "roast"} <= set(STYLE_TEMPLATES)
    assert all(v.strip() for v in STYLE_TEMPLATES.values())


def test_reviewer_rubric_describes_output_fields():
    assert REVIEWER_RUBRIC.strip()
    assert "approved" in REVIEWER_RUBRIC
    assert "feedback" in REVIEWER_RUBRIC
