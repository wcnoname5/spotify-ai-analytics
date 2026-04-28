# Spotify AI Analytics — MCP Server

Local MCP server that exposes Spotify history analytics and playback control as tools for Claude Desktop or Claude Code.

---

## Prerequisites

- Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Spotify account (free or Premium — analytics tools work free, playback requires Premium)
- A Spotify Developer app (free, takes 2 minutes to create)

---

## 1-minute setup summary

```bash
# 1. Install dependencies
uv sync

# 2. Set SPOTIFY_CLIENT_ID in .env (only key you need to find manually — see Section 2)
cp .env.example .env

# 3. Initialize DB, connect Spotify account, and optionally import your full history.
#    Place your Streaming_History_Audio_*.json files in data/spotify_history/ first (optional).
#    TOKEN_ENCRYPT_KEY would be auto-generated (no need to prepare manually)
uv run python scripts/setup.py

# 4. (Optional) Fill the gap between your JSON history and today, or fetch recent plays if you skipped JSON.
uv run python scripts/sync_api.py

# 5. Add the server to Claude (see Section 4)
```

---

## Section 2 — Required environment variables

Open `.env` in a text editor. Fill in the one required value:

### `SPOTIFY_CLIENT_ID`

1. Go to [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in.
2. Click **Create app**.
3. Fill in any name and description. Set **Redirect URIs** to exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   > ⚠️ Use `127.0.0.1`, NOT `localhost` — Spotify blocked `localhost` redirects in November 2025.
4. Accept the terms and click **Save**.
5. On the app overview page, copy the **Client ID** (a 32-character hex string).
6. Paste it into `.env`:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   ```
   > Note: `SPOTIFY_CLIENT_SECRET` is **not needed** — this server uses PKCE (no secret required).

### `TOKEN_ENCRYPT_KEY`

**You don't need to generate this manually.** When you run `scripts/setup.py` and `TOKEN_ENCRYPT_KEY` is not set, the script auto-generates a Fernet key and writes it to your `.env` file automatically.

If you ever need to set it manually (e.g., restoring from backup):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `.env` as `TOKEN_ENCRYPT_KEY=<value>`.

> Keep this key safe — it encrypts your stored Spotify tokens. If you lose it, re-run OAuth to get new tokens.

### `SPOTIFY_USER_ID` (optional but recommended)

Your Spotify username — shown at [https://www.spotify.com/account/overview/](https://www.spotify.com/account/overview/) under **Username**.

```
SPOTIFY_USER_ID=your_username
```

If omitted, defaults to `"default"`.

---

## Section 3 — Loading your listening history and initate the DB

### Full history — Spotify JSON export (recommended)

Spotify can export your entire Extended Streaming History (all plays ever).

1. Go to [https://www.spotify.com/account/privacy/](https://www.spotify.com/account/privacy/).
2. Scroll to **Download your data** → select **Extended streaming history**.
3. Click **Request data**. Spotify emails you a download link within a few days.
4. Unzip the download. You'll have files named `Streaming_History_Audio_*.json`.
5. Place these files in `data/spotify_history/` **before** running `setup.py`.
   `setup.py` imports them automatically — no extra command needed.
  - *Note:* If you didn't place the JSON files, `setup.py` won't load the data but it will still initate the databse.


### Recent plays only — Spotify API (instant, no JSON needed)

```bash
uv run python scripts/sync_api.py
```

> **Note:** The Spotify recently-played API only holds your last ~50 plays. It cannot recover months of history — only the JSON export can do that.

Run `sync_api.py` anytime to stay up to date (the `sync_history` MCP tool does the same thing).

---

## Section 4 — Connecting to Claude

### Claude Code (CLI)

Add to your project's `.claude/settings.json` or your user settings file, claude code can then connect to this MCP server in project level:

```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "uv",
      "args": ["run", "python", "apps/mcp/server.py"],
      "cwd": "/absolute/path/to/spotify-ai-analytics"
    }
  }
}
```

Restart Claude Code after saving.

### Claude Desktop (macOS / Windows)

Open the Claude Desktop config file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the `mcpServers` block: (Windows)

```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "uv",
      "args": ["run", "python", "C:\\Path\\Tospotify-ai-analytics\\apps\\mcp\\server.py"],
      "cwd": "C:\\Path\\To\\spotify-ai-analytics"
    }
  }
}
```
For best practice, the application (& `uv`) should be written with direct path. `\\` for windows, `/` for macOS.

If the having trouble with `uv`, try use the python intepreter in `.venv` as command to initate the MCP server directly.

```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "C:\\Path\\To\\spotify-ai-analytics\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Path\\To\\spotify-ai-analytics\\apps\\mcp\\server.py"],
      "cwd": "C:\\Path\\To\\spotify-ai-analytics"
    }
  }
}
```

Restart Claude Desktop after saving.

---

## Section 5 — First-time auth walkthrough

After adding the server to Claude, ask Claude:

> "Run setup_check and tell me what's missing."

Claude will call the `setup_check` tool and give you a step-by-step list of what still needs to be done.

When the OAuth step comes up, Claude will say to run:
```bash
uv run python scripts/setup.py
```

This opens your browser to Spotify's login page. After you approve, the browser shows "Authentication complete" and tokens are saved locally. You only need to do this once — tokens auto-refresh.

---

## Section 6 — Available MCP tools

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
→ Run the OAuth flow: `uv run python scripts/setup.py`

**"SPOTIFY_CLIENT_ID is not set"**
→ Check your `.env` file has `SPOTIFY_CLIENT_ID=...` (no quotes, no spaces around `=`)

**OAuth browser doesn't open / times out**
→ The callback server listens on port 8888. Make sure nothing else is using it.
→ If you're in a headless environment, the auth script will print a URL — open it manually.

**Playback tools return "Spotify Premium required"**
→ Playback control (play, pause, skip, volume) requires a Spotify Premium subscription.

**DB is empty after import**
→ Check that your JSON files are named `Streaming_History_Audio_*.json` or `Streaming_History_Video_*.json`.
→ Run: `uv run python scripts/setup.py`

**"Token decrypt failed" or "Invalid token"**
→ Your `TOKEN_ENCRYPT_KEY` may have changed. Generate a new key, update `.env`, and re-run OAuth.
