# Spotify AI Analytics

A local-first Spotify analytics toolkit — MCP server for Claude Desktop/Code, a Streamlit dashboard with AI-generated listening reports, and a SQLite-backed data pipeline. All set up with a single CLI command.

> **Legacy docs & App** (original Streamlit web app): see the [`deploy` branch](../../tree/deploy).

---

## What it does

- **MCP**
  - **Analytics** — ask Claude things like "What were my top artists last month?" or "How has my listening changed since 2023?"
  - **Playback control** — play, pause, skip, set volume, add to queue (Spotify Premium required)
- **Dashboard and Report Generation**
  - **Dashboard** — Plotly charts for listening trends, top artists/tracks, and activity patterns
  - **AI reports** — LangGraph-powered drafter/reviewer pipeline generates weekly or monthly listening reviews

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (the wizard walks you through creating one)

---

## MCP Server Setup (Claude Desktop)

### 1. Run the setup wizard

```bash
uvx --from spotify-analytics-mcp spotify-mcp setup
```

The wizard walks you through each step (already-completed steps are skipped automatically):

1. Create a Spotify developer app and paste the Client ID
2. OAuth login (opens your browser)
3. Import listening history (from Spotify's JSON export, or sync recent plays)
4. Register the MCP server with Claude Desktop

### 2. Connect Claude Desktop

After the wizard finishes, it prints a JSON snippet like this:

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "command": "uvx",
      "args": ["--from", "spotify-analytics-mcp", "spotify-mcp", "serve"]
    }
  }
}
```

To add it to Claude Desktop:

1. Open Claude Desktop, click the menu (☰) in the top-left
2. (If you not enable developmer mode yet) Go to **Help > Troubleshooting > Enable Developer Mode**
3. Go to **Developer > Open App Config File...** to open `claude_desktop_config.json`
4. Paste the snippet above (merge into the existing `mcpServers` object if you have other servers)
5. Click **Developer > Reload MCP Configuration** (or restart Claude Desktop)
6. In a new chat, click **+ > Connectors** — you should see **spotify-mcp** in the list

### 3. Try it out

Click **+ > Connectors > Listening Report Generator** to generate your personal listening report, or just ask Claude about your listening history.

---

## Dashboard & AI Reports

The dashboard is an optional extra — the MCP server works without it.

### Install

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp setup
```

Using the `[dashboard]` extra triggers two additional (optional) wizard steps:

- **LLM provider key** — choose Gemini (recommended, free tier) or OpenAI. Required for AI reports; the dashboard charts work without it.
- **Langfuse keys** — optional observability for the AI report pipeline. Skip if you don't use Langfuse.

You can always add or change these keys later in your `.env` file (run `spotify-mcp path` to find it).

### Launch

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard
```

### Keeping history up to date

Sync the latest plays from Spotify's API:

```bash
uvx --from spotify-analytics-mcp spotify-mcp sync
```

or click the Sync botton on the top-right in dashboard view. 

## CLI Reference

| Command | Description |
|---|---|
| `spotify-mcp setup` | Interactive setup wizard (skips completed steps) |
| `spotify-mcp serve` | Start the MCP server over stdio (used by Claude Desktop) |
| `spotify-mcp dashboard` | Launch the Streamlit dashboard (requires `[dashboard]` extra) |
| `spotify-mcp sync` | Sync recent plays from Spotify API |
| `spotify-mcp doctor` | Check environment readiness (JSON report) |
| `spotify-mcp import-history` | Import from Spotify's JSON data export |
| `spotify-mcp reauth` | Re-run OAuth flow |
| `spotify-mcp path` | Show config and data directory locations |

---

## Tech Stack

| Layer | Choice |
|---|---|
| MCP framework | FastMCP (Python MCP SDK) |
| AI reports | LangGraph (drafter → reviewer pipeline) |
| Observability | Langfuse (optional) |
| Local storage | SQLite (encrypted token store) |
| Data processing | Polars + Pydantic |
| Dashboard | Streamlit + Plotly |
| OAuth | Authorization Code with PKCE |

---

## Project Layout

```
packages/core/        # Shared library: analytics, db, report pipeline, spotify_client
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server + CLI + Streamlit dashboard
data/                 # Local SQLite DBs and JSON exports (not committed)
```