"""Tests for spotify_core.report.observability and prompts."""
import re
import tomllib
from pathlib import Path

from spotify_core.report.prompts import report_struct

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


def test_only_custom_ranges_skip_period_comparison():
    """The two-playbook split turns on exactly one thing: a custom range must not be
    compared against a preceding period (it has no aligned one), every calendar type
    must be. Nothing else distinguishes them."""
    custom = report_struct("custom")
    assert "不要與其他區間比較" in custom
    for period_type in ("weekly", "monthly", "quarterly", "yearly"):
        assert "對比" in report_struct(period_type)
        assert report_struct(period_type) != custom
