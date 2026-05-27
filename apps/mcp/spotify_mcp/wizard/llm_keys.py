"""Wizard step: optionally configure LLM provider API keys."""
from __future__ import annotations

import os

from rich.console import Console

from spotify_core import env_file, paths

_PROVIDERS = {
    "1": ("GEMINI_API_KEY", "Gemini (Google)"),
    "2": ("OPENAI_API_KEY", "OpenAI"),
}


def _has_any_llm_key() -> bool:
    for env_var, _ in _PROVIDERS.values():
        if env_file.read_key(paths.env_file(), env_var):
            return True
    return False


def run_step(console: Console) -> None:
    """Prompt user for LLM API keys. Entirely skippable."""
    if _has_any_llm_key():
        console.print("[dim]LLM API key already configured — skipping.[/dim]")
        return

    answer = console.input(
        "\n[bold]Set up an LLM provider for AI reports? (y/N):[/bold] "
    ).strip().lower()
    if answer not in ("y", "yes"):
        console.print("[dim]Skipped LLM setup. You can add keys to .env later.[/dim]")
        return

    console.print("  [bold]1.[/bold] Gemini (Google) — recommended, free tier available")
    console.print("  [bold]2.[/bold] OpenAI")
    choice = console.input("[bold]Choose provider (1/2):[/bold] ").strip()

    if choice not in _PROVIDERS:
        console.print("[yellow]Invalid choice — skipping LLM setup.[/yellow]")
        return

    env_var, provider_name = _PROVIDERS[choice]
    key = console.input(f"[bold]Paste your {provider_name} API key:[/bold] ").strip()
    if not key:
        console.print("[yellow]Empty key — skipping.[/yellow]")
        return

    env_file.upsert(paths.env_file(), env_var, key)
    os.environ[env_var] = key
    console.print(f"[green]{provider_name} API key saved.[/green]")
