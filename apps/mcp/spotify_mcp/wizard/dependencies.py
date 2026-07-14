"""Dependency checks for the optional AI-report extra (the `[report]` extra)."""
from __future__ import annotations

import importlib.util

_REPORT_IMPORTS = (
    "langchain_google_genai",
    "langchain_openai",
    "langfuse",
)


def dashboard_available() -> bool:
    """True when the `[report]` extra's startup dependencies are importable.

    Historically these deps shipped alongside a Streamlit dashboard (hence
    the name); the dashboard is gone but the wizard still uses this check to
    decide whether to run the LLM/Langfuse setup steps for AI reports.
    """
    return all(importlib.util.find_spec(name) is not None for name in _REPORT_IMPORTS)
