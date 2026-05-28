"""Tests for spotify_core.report.observability and prompts."""
from spotify_core.report.observability import get_trace_url
from spotify_core.report.prompts import compose_reviewer_system


def test_get_trace_url_none_without_callbacks():
    assert get_trace_url([]) is None


def test_reviewer_rubric_describes_output_fields():
    rubric = compose_reviewer_system("listening_review", "dummy playbook")
    assert rubric.strip()
    assert "approved" in rubric
    assert "feedback" in rubric
