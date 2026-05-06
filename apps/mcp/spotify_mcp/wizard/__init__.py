"""Wizard package — interactive setup flow for spotify-mcp."""
from __future__ import annotations

from pathlib import Path


def run_wizard(
    install_claude_desktop: bool = False,
    import_path: Path | None = None,
) -> None:
    """Run the interactive setup wizard.

    Raises:
        NotImplementedError: Wizard is not yet implemented.
    """
    raise NotImplementedError("run_wizard is not yet implemented")
