# Spotify AI Analytics

A local MCP server that connects Claude Desktop / Claude Code to your Spotify listening history — query your stats, control playback, and build AI-generated playlists, all through natural language.

> **Legacy docs** (original Streamlit web app): see the [`deploy` branch](../../tree/deploy).

---

## What it does

- **Analytics** — ask Claude things like "What were my top artists last year?" or "How has my taste changed since 2022?"
- **Playback control** — play, pause, skip, set volume, add to queue (Spotify Premium required)
- **AI playlists** — generate and save playlists based on your listening history
- **Memory** — Claude remembers your preferences across conversations (not released yet)

---

## Quick start

See **[doc/MCP_QUICKSTART.md](doc/MCP_QUICKSTART.md)** for the full setup guide.

The short version:

```bash
# 1. Install dependencies
uv sync

# 2. Set SPOTIFY_CLIENT_ID in .env
cp .env.example .env

# 3. Initialize DB and authenticate
uv run python scripts/setup.py

# 4. Add to Claude (CLI)
claude mcp add spotify-analytics -- uv run python apps/mcp/server.py
```

---

## Tech stack

| Layer | Choice |
|---|---|
| MCP framework | `mcp` Python SDK |
| Agent framework | LangGraph |
| Local storage | SQLite |
| Data processing | Polars |
| OAuth | PKCE |

---

## Project layout

```
packages/core/        # Shared packages: analytics, agent, memory, db, spotify_client
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server entry point
apps/web/             # Web app (Phase 2, skeleton only)
data/                 # Local SQLite DBs and JSON exports
scripts/              # Setup, sync, and inspection scripts
```

Phase 2 (FastAPI + Streamlit web app) is planned but deferred. See [ARCHITECTURE.md](doc/ARCHITECTURE.md) for the full spec.
