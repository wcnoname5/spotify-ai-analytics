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

Before starting, you need to create an app tor get the `SPOTIFY_CLIENT_ID` (check **[doc/MCP_QUICKSTART.md](doc/MCP_QUICKSTART.md#spotify_client_id)** for details).

The short version: you need to run these scripts in your terminal:

```bash
# 1. Install dependencies
uv sync

# 2. Create .env and go set SPOTIFY_CLIENT_ID in .env file
cp .env.example .env

# 3. setup for DB initialization, Oath authentication
uv run python scripts/setup.py
```

### MCP connection in Claude Desktop (Recommended for GUI users)

1. In Claude Desktop, click the settings (≡ mark in the top-left), go to `Help > Troubleshooting > Enable Developer Mode`. After you enable Developer Mode, go to `Developer > Open App Config File...` to open `claude_desktop_config.json` and add this block:

    ```json
    {
    "mcpServers": {
        "spotify-analytics": {
        "command": "uv",
        "args": ["run", "python", "C:\\Path\\To\\spotify-ai-analytics\\apps\\mcp\\server.py"],
        "cwd": "C:\\Path\\To\\spotify-ai-analytics"
        }
    }
    }
    ```

    For best results, use absolute paths for `args` and `cwd`. Use `\\` for Windows and `/` for macOS.

2. Click `Developer > Reload MCP Configuration` in Claude Desktop (or simply restart) after saving.

3. Click `+ > Connectors` in the chat box; you should see `spotify-analytics` in the list.

### MCP connection in Claude CLI

```bash
# 3. Add to Claude (CLI)
claude mcp add spotify-analytics -- uv run python apps/mcp/server.py
# 4. Check if the connection is successful
claude mcp list
```

### How do I know if I'm doing it right?

If you've connected to Claude successfully, you can ask it directly!

Click `+ > Connectors > Add from spotify-analytics` in the chat box. We provide a system prompt `Spotify-Analytic MCP Guide` to help you get started.

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
