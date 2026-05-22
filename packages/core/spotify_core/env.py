"""Shared dotenv helpers used by apps to ensure .env is loaded before Settings.

This module centralizes the small per-app logic (loading platform .env and
providing runtime helpers like `get_client_id`) so app `config.py` files can
remain thin wrappers that only call these helpers.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
from loguru import logger

from spotify_core import paths

def ensure_dotenv_loaded() -> None:
    """Load the platform config `.env` if present, then a cwd .env fallback.

    Idempotent — safe to call multiple times.
    """
    try:
        if paths.env_file().exists():
            load_dotenv(paths.env_file())
        # fallback: load a .env from cwd if present (dev convenience)
        load_dotenv(override=False)
    except Exception:
        logger.exception("Failed to load .env file")


def get_client_id() -> str:
    """Return SPOTIFY_CLIENT_ID from the environment (ensures .env loaded)."""
    return os.getenv("SPOTIFY_CLIENT_ID", "")


def get_fernet_key() -> bytes:
    """Return TOKEN_ENCRYPT_KEY as bytes (ensures .env loaded)."""
    raw = os.getenv("TOKEN_ENCRYPT_KEY", "")
    return raw.encode() if raw else b""
