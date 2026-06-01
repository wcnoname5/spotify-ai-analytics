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

## Install

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/)

```bash
uvx --from spotify-analytics-mcp spotify-mcp setup
```
The wizard will guide you through:

- Creating a Spotify developer app
- OAuth login
- Importing your listening history
- Registering with Claude Desktop

### Launch the dashboard

Run `uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard` (or, from a dev checkout, `uv run spotify-mcp dashboard`).

1. run `spotify-mcp doctor`
2. if setup is incomplete, open `spotify-mcp setup`
3. start the dashboard with `uv run spotify-mcp dashboard`

### MCP connection in Claude Desktop (Recommended for GUI users)

1. In Claude Desktop, click the settings (≡ mark in the top-left), go to `Help > Troubleshooting > Enable Developer Mode`. After you enable Developer Mode, go to `Developer > Open App Config File...` to open `claude_desktop_config.json` and add this block:

  ```json
  {
    "mcpServers": {
      "spotify-analytics": {
        "command": "spotify-mcp",
        "args": ["serve"]
      }
    }
  }
  ```

2. Click `Developer > Reload MCP Configuration` in Claude Desktop (or simply restart) after saving.

3. Click `+ > Connectors` in the chat box; you should see `spotify-analytics` in the list.


## Examaple Use

Click `+ > Connectors > Listening Report Generator` prompt to generate your personal listening history report!

---
## Tech stack

| Layer | Choice |
|---|---|
| MCP framework | `mcp` Python SDK |
| Agent framework | LangGraph (On progress) |
| Local storage | SQLite |
| Data processing | Polars |
| OAuth | PKCE |

---

## Project layout

```
packages/core/        # Shared packages: analytics, agent, memory, db, spotify_client
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server entry point + Streamlit dashboard
data/                 # Local SQLite DBs and JSON exports
scripts/              # Setup, sync, and inspection scripts
```