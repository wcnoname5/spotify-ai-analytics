"""Shared helpers for the MCP server layer (not part of core — MCP-specific only)."""
from __future__ import annotations
from datetime import datetime

_AUTH_ERROR_KEYWORDS = ("No token found", "No stored token", "Cannot refresh")


def utc_iso_to_local(utc_iso: str | None) -> str | None:
    """Convert a UTC ISO timestamp (e.g. '2024-01-15T08:30:00Z') to the system local timezone.

    Returns the original string unchanged if it cannot be parsed.
    Returns None if input is None.
    """
    if utc_iso is None:
        return None
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        return dt.astimezone().isoformat()
    except (ValueError, TypeError):
        return utc_iso


def enrich_auth_error(result: dict, user_id: str) -> dict:
    """If result contains a Spotify auth error, add requires_auth and auth_command fields.

    Leaves non-error and non-auth-error dicts untouched.
    """
    error_msg = result.get("error", "")
    if any(kw in error_msg for kw in _AUTH_ERROR_KEYWORDS):
        return {
            **result,
            "requires_auth": True,
            "auth_command": (
                f"uv run python scripts/init_db.py --auth --user-id {user_id}"
            ),
        }
    return result
