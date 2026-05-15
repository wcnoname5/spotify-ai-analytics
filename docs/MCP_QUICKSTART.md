# Spotify AI Analytics — MCP Server

Local MCP server that exposes Spotify history analytics and playback control as tools for Claude Desktop or Claude Code.

---

## Prerequisites

- Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Spotify account (free or Premium — analytics tools work free, playback requires Premium)
- A Spotify Developer app (Premium, takes 2 minutes to create)

---

## 1-minute setup summary

*This doc is under development*
```bash
# 1. build dist
uv build apps/mcp

# 2. install packages
uv tools install apps/mcp

# 3. terminal command
spotify-mcp setup

# 4. (Optional) Fill the gap between your JSON history and today, or fetch recent plays if you skipped JSON.
spotify-mcp sync
```

---

## Section 2 — `spotify-mcp` CLI command walkthrough

| Command | What it does |
|---------|-------------|
| `spotify-mcp setup` | Interactive wizard: enters Spotify app credentials, runs OAuth, optionally imports JSON history |
| `spotify-mcp doctor` | Checks environment readiness and prints a JSON report; exits 0 if ready, 1 if not |
| `spotify-mcp reauth` | Re-runs the Spotify OAuth PKCE flow (use when tokens expire or are revoked) |
| `spotify-mcp sync` | Fetches the most recent ~50 plays from the Spotify API and upserts them into the local DB |
| `spotify-mcp serve` | Starts the MCP server over stdio — invoked by Claude Desktop / Claude Code, not usually run directly |

---

## Section 3 — Loading history & Database initialization

Then the setup wizard will request for your listening history.

### Full history — Spotify JSON export (Recommended)

Spotify can export your full Extended Listening History.

1. Request your data at [spotify.com/account/privacy](https://www.spotify.com/account/privacy/) (select **Extended streaming history**).
2. Once received (~few days), unzip and place `Streaming_History_Audio_*.json` files in `data/spotify_history/`.
3. Run `spotify-mcp setup` — the wizard will detect the files and offer to import them.

### Recent plays — Spotify API (Instant)

```bash
spotify-mcp sync
```

> **Note:** The API only holds your last ~50 plays. Deep history requires the JSON export.

---

## Section 4 — Connecting to Claude

You can choose connecting to Claude Desktop (GUI, but much tricky to connect) or Claude CLI.

### Claude Desktop (macOS / Windows)

1. Enable Developer Mode: `Settings > Help > Troubleshooting > Enable Developer Mode`.
2. Open Config: `Developer > Open App Config File...` and add to `mcpServers`:

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

3. Click `Developer > Reload MCP Configuration`. You should see `Spotify-Analytic` in the `+ > Connectors` menu.

<details>
<summary><i>If Claude Desktop cannot find <code>spotify-mcp</code>:</i></summary>

Use the full path to the installed binary. Find it with `where spotify-mcp` (Windows) or `which spotify-mcp` (macOS/Linux):
```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "C:\\Users\\you\\.local\\bin\\spotify-mcp",
      "args": ["serve"]
    }
  }
}
```
</details>

### Claude Code (CLI)

At project root run the command in terminal
```bash
claude mcp add spotify-analytics -- spotify-mcp serve
```

Restart Claude Code after saving. Run the command to check if the MCP server is connected successfully.
```bash
claude mcp list
```

---

## Section 6 — Available MCP tools

### Prompt

| Prompt | How to activate | What it does |
|--------|----------------|-------------|
| `how_to_use` | Ask Claude: *"Use the how_to_use prompt"* | Loads the full onboarding guide — explains every tool and the setup sequence |

### Tools

| Tool | Description | Requires auth |
|------|-------------|---------------|
| `setup_check` | Diagnose configuration — start here if anything is broken | No |
| `sync_history` | Fetch 50 most recent plays from Spotify API into local DB | Yes |
| `import_history_from_json` | Bulk-import a folder of Spotify JSON export files | No |
| `get_listening_summary` | Total plays, unique artists/tracks, date range | No |
| `get_top_artists` | Top artists by listening time (filterable by date range) | No |
| `get_top_tracks` | Top tracks by play count (filterable by date range) | No |
| `get_now_playing` | Currently playing track | Yes |
| `play_track` | Play a specific track URI — **Premium required** | Yes |
| `pause_playback` | Pause playback — **Premium required** | Yes |
| `skip_track` | Skip to next track — **Premium required** | Yes |
| `set_volume` | Set volume 0–100 — **Premium required** | Yes |
| `add_to_queue` | Add a track to the playback queue — **Premium required** | Yes |
| `create_playlist` | Create a playlist and populate it with track URIs | Yes |
| `remember_preference` | Store a preference in long-term memory | No |
| `get_memory_summary` | Retrieve all stored preferences and facts | No |

---

## Troubleshooting

**"No Spotify tokens found" on startup**
→ Run the OAuth flow: `spotify-mcp reauth`

**"SPOTIFY_CLIENT_ID is not set"**
→ Check your `.env` file has `SPOTIFY_CLIENT_ID=...` (no quotes, no 
s around `=`)

**OAuth browser doesn't open / times out**
→ The callback server listens on port 8888. Make sure nothing else is using it.
→ If you're in a headless environment, the auth script will print a URL — open it manually.

**Playback tools return "Spotify Premium required"**
→ Playback control (play, pause, skip, volume) requires a Spotify Premium subscription.

**DB is empty after import**
→ Check that your JSON files are named `Streaming_History_Audio_*.json` or `Streaming_History_Video_*.json`.
→ Run: `spotify-mcp setup --import <path-to-folder>`

**"Token decrypt failed" or "Invalid token"**
→ Your `TOKEN_ENCRYPT_KEY` may have changed. Generate a new key, update `.env`, and re-run OAuth.

**"Cannot find my `claude_desktop_config.json`"**
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

## Developer Debug

Run official MCP inspector (requires Node.js) in local server:
```bash
npx @modelcontextprotocol/inspector uv run --package spotify-analytics-mcp spotify-mcp serve
```
or using FastMCP CLI
```bash
uv run fastmcp dev inspector
```