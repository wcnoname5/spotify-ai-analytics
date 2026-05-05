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

See **[MCP_QUICKSTART.md](doc/MCP_QUICKSTART.md)** for the full setup guide.

Before starting, you need to: 
1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).

2. Create an app tor get the `SPOTIFY_CLIENT_ID` (check Section**[`SPOTIFY_CLIENT_ID`](doc/MCP_QUICKSTART.md#spotify_client_id)** for details).

3. (*Optional but recommended*) Request your [Spotify streaming history](https://www.spotify.com/account/privacy/) and place the json files under `data/spotify_history/` folder (See also **[Section 3](doc/MCP_QUICKSTART.md#section-3--loading-history--database-initialization)**).

Then you need to run these scripts in your terminal:

```bash
# 1. Install dependencies
uv sync

# 2. Create .env and go set SPOTIFY_CLIENT_ID in .env file
cp .env.example .env

# 3. setup for DB initialization, Oath authentication
uv run python scripts/setup.py
```
## MCP client setup

We provide setup instructions for the clients below: Claude Desktop, Claude CLI, and VS code.

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

#### How do I know if I'm doing it right?

If you've connected to Claude Desktop successfully, you can ask it directly!

Click `+ > Connectors > Add from spotify-analytics` in the chat box. We provide a system prompt `Spotify-Analytic MCP Setup Guide` to help you get started.

### MCP connection in Claude CLI

```bash
# 3. Add to Claude (CLI)
claude mcp add spotify-analytics -- uv run python apps/mcp/server.py
# 4. Check if the connection is successful
claude mcp list
```
### MCP connection in VS Code 

We have already done the connection configuration in the `.vscode/mcp.json`. Open this project with VScode should connect to the MCP server.

## Example Usage

- Use `Listening Report Generator` Prompt Template (in Claude Desktop, click `+ > Connectors > Add from spotify-analytics` in the chat box). Claude can generate the detailed analysis report based on your spotify listening history.

Or you can simply ask:
- Whose my favotie artist in 2023?
- Create a playlsit consists of my most played songs in 2025?
- recommend me some new songs based on my taste.

---
## Tech stack

| Layer | Choice |
|---|---|
| MCP framework | FastMCP |
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
