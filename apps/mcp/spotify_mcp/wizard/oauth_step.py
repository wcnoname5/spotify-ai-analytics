"""Wizard OAuth step — handles Spotify OAuth authorisation flow."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def run_oauth(console: "Console | None" = None, force: bool = False) -> None:
    """Run the OAuth authorisation step.

    Args:
        console: Optional Rich Console instance for output.
        force:   When True, re-authorise even if a valid token already exists.

    Raises:
        NotImplementedError: OAuth step is not yet implemented.
    """
    raise NotImplementedError("run_oauth is not yet implemented")
