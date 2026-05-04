"""Shared helpers for the MCP server layer (not part of core — MCP-specific only)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from spotify_core.spotify_client.errors import (
    SpotifyAuthError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
)

logger = logging.getLogger(__name__)


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
        logger.warning("utc_iso_to_local: failed to parse %r, returning unchanged", utc_iso)
        return utc_iso


def to_error_response(
    exc: Exception,
    user_id: str,
    *,
    list_devices: Optional[Callable[[], list]] = None,
) -> dict:
    """Convert an exception raised by the core layer into an MCP-friendly error dict.

    Recognised typed exceptions get enriched output:

    - ``SpotifyAuthError``: adds ``requires_auth`` and ``auth_command``.
    - ``SpotifyPremiumRequiredError``: returns the canonical Premium message.
    - ``SpotifyNoActiveDeviceError``: when ``list_devices`` is provided, includes
      the available device list and a ``hint``.

    Other exceptions are returned as ``{"error": str(exc)}``.
    """
    if isinstance(exc, SpotifyAuthError):
        logger.warning("auth error for user=%r: %s", user_id, exc)
        return {
            "error": str(exc),
            "requires_auth": True,
            "auth_command": (
                f"uv run python scripts/init_db.py --auth --user-id {user_id}"
            ),
        }
    if isinstance(exc, SpotifyPremiumRequiredError):
        return {"error": "Spotify Premium required for playback control."}
    if isinstance(exc, SpotifyNoActiveDeviceError):
        devices: list = []
        if list_devices is not None:
            try:
                devices = list_devices()
            except Exception as inner:
                logger.warning("Failed to list devices while enriching error: %s", inner)
        return {
            "error": "No active Spotify device found. Open Spotify on a device first.",
            "available_devices": devices,
            "hint": "Pass a device_id from available_devices to target a specific device.",
        }
    return {"error": str(exc)}
