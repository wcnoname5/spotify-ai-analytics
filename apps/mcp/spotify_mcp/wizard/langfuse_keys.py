"""Wizard step: optionally configure Langfuse observability keys."""
from __future__ import annotations

import os

from rich.console import Console

from spotify_core import env_file, paths

_KEYS = [
    ("LANGFUSE_PUBLIC_KEY", "Langfuse Public Key"),
    ("LANGFUSE_SECRET_KEY", "Langfuse Secret Key"),
    ("LANGFUSE_BASE_URL", "Langfuse Base URL (e.g. https://cloud.langfuse.com)"),
]


def run_step(console: Console) -> None:
    """Prompt user for Langfuse keys. Entirely skippable."""
    from spotify_core.config import settings

    if settings.langfuse_configured:
        console.print("[dim]Langfuse already configured — skipping.[/dim]")
        return

    answer = console.input(
        "\n[bold]Set up Langfuse for AI report tracing? (y/N):[/bold] "
    ).strip().lower()
    if answer not in ("y", "yes"):
        console.print("[dim]Skipped Langfuse setup. Reports work fine without it.[/dim]")
        return

    for env_var, label in _KEYS:
        value = console.input(f"[bold]{label}:[/bold] ").strip()
        if not value:
            console.print("[yellow]Empty value — aborting Langfuse setup.[/yellow]")
            return
        env_file.upsert(paths.env_file(), env_var, value)
        os.environ[env_var] = value

    console.print("[green]Langfuse configured. Traces will appear in your dashboard.[/green]")
