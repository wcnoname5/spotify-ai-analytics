"""Dependency checks for the optional dashboard extra."""
from __future__ import annotations

import importlib.util

_DASHBOARD_IMPORTS = (
    "streamlit",
    "plotly",
    "langchain_google_genai",
    "langchain_openai",
    "langfuse",
)


def dashboard_available() -> bool:
    """True when the [dashboard] extra's startup dependencies are importable."""
    return all(importlib.util.find_spec(name) is not None for name in _DASHBOARD_IMPORTS)
