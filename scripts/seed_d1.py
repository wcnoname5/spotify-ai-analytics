"""Seed D1 from the local SQLite data via the Worker (one-shot, rerun-safe).

Thin wrapper: the implementation moved to `spotify_mcp.cloud` / `spotify_mcp.seed`
so packaging bundles a single exe. Prefer `spotify-mcp cloud seed`; this stays for
docs/DEPLOY.md and muscle memory.

Usage:
    WORKER_URL=... WORKER_AUTH_TOKEN=... uv run python scripts/seed_d1.py [--force] [--tokens-only]
"""
import os
import sys

from spotify_mcp import cloud

if __name__ == "__main__":
    sys.exit(
        cloud.seed(
            worker_url=os.environ.get("WORKER_URL", ""),
            worker_token=os.environ.get("WORKER_AUTH_TOKEN", ""),
            force="--force" in sys.argv,
            tokens_only="--tokens-only" in sys.argv,
        )
    )
