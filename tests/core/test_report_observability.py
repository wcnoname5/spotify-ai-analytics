"""Packaging guard for the published core[report] extra."""
import re
import tomllib
from pathlib import Path

_CORE_PYPROJECT = Path(__file__).resolve().parents[2] / "packages" / "core" / "pyproject.toml"


def _dep_names(deps: list[str]) -> set[str]:
    """Distribution names from a PEP 508 dependency list, lowercased."""
    return {re.split(r"[<>=!~ \[;]", d, maxsplit=1)[0].strip().lower() for d in deps}


def test_report_extra_declares_what_the_report_imports():
    """The published core[report] extra must ship every package the report path
    imports — including the langchain meta-package, which
    `langfuse.langchain.CallbackHandler` imports bare (langchain-core alone is not
    enough). A clean install is the only other place a missing one shows up."""
    extras = tomllib.loads(_CORE_PYPROJECT.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    assert {"langchain", "langchain-core", "langchain-google-genai", "langchain-openai",
            "langfuse"} <= _dep_names(extras["report"])
