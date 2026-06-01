"""Tests for spotify_core.report.observability and prompts."""
import re
import tomllib
from pathlib import Path

from spotify_core.report.observability import get_trace_url
from spotify_core.report.prompts import compose_reviewer_system

_CORE_PYPROJECT = Path(__file__).resolve().parents[2] / "packages" / "core" / "pyproject.toml"


def _dep_names(deps: list[str]) -> set[str]:
    """Distribution names from a PEP 508 dependency list, lowercased."""
    return {re.split(r"[<>=!~ \[;]", d, maxsplit=1)[0].strip().lower() for d in deps}


def test_report_extra_declares_langchain():
    """`langfuse.langchain.CallbackHandler` does a bare `import langchain`, so the
    published core[report] extra must ship the langchain meta-package — langchain-core
    alone is not enough. In the dev workspace this is masked by the (unpublished) root
    pyproject, so only a clean install catches it. See report/observability.py."""
    extras = tomllib.loads(_CORE_PYPROJECT.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    assert "langchain" in _dep_names(extras["report"])


def test_get_trace_url_none_without_callbacks():
    assert get_trace_url([]) is None


def test_reviewer_rubric_describes_output_fields():
    rubric = compose_reviewer_system("listening_review", "dummy playbook")
    assert rubric.strip()
    assert "approved" in rubric
    assert "feedback" in rubric
