# Spotify AI Analytics — MCP Server

Local MCP server that exposes Spotify history analytics and playback control as tools for Claude Desktop or Claude Code.

---

## Prerequisites

- Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Spotify account (free or Premium — analytics tools work free, playback requires Premium)
- A Spotify Developer app (Premium, takes 2 minutes to create)

---

## 1-minute setup summary

```bash
# 1. Install dependencies
uv sync

# 2. Set SPOTIFY_CLIENT_ID in .env (only key you need to find manually — see Section 2)
cp .env.example .env

# 3. Initiate the DB and Authentication. (Or you can tell Claude to run this for you, see section 5) 
uv run python scripts/setup.py

# 4. (Optional) Fill the gap between your JSON history and today, or fetch recent plays if you skipped JSON.
uv run python scripts/sync_api.py
```

---

## Section 2 — Required environment variables

Open `.env` in a text editor. Fill in the one required value:

### `SPOTIFY_CLIENT_ID`

1. Log in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
  - *Note:* Per [Spotify's Feb 2026 update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security), creating new apps may require a Premium account. 
2. Click **Create app** and set **Redirect URIs** to exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   > ⚠️ Use `127.0.0.1`, NOT `localhost`.
3. Copy the **Client ID** and paste it into `.env`:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   ```
   > Note: `SPOTIFY_CLIENT_SECRET` is **not needed** (this server uses PKCE).

<details>
 <summary> <strong> Optional Fields  </strong> </summary>

### `TOKEN_ENCRYPT_KEY`
**You don't need to generate this manually.**

When you run `scripts/setup.py` and `TOKEN_ENCRYPT_KEY` is not set, the script auto-generates a Fernet key and writes it to your `.env` file automatically.

If you ever need to set it manually (e.g., restoring from backup):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `.env` as `TOKEN_ENCRYPT_KEY=<value>`.

> Keep this key safe — it encrypts your stored Spotify tokens. If you lose it, re-run OAuth to get new tokens.

### Optional: `SPOTIFY_USER_ID`

Your Spotify username — shown at [https://www.spotify.com/account/overview/](https://www.spotify.com/account/overview/) under **Username**.

```
SPOTIFY_USER_ID=your_username
```

If omitted, defaults to `"default"`.

</details>

---

## Section 3 — Loading history & Database initialization

### Full history — Spotify JSON export (Recommended)

Spotify can export your full Extended Listening History.

1. Request your data at [spotify.com/account/privacy](https://www.spotify.com/account/privacy/) (select **Extended streaming history**).
2. Once received (~few days), unzip and place `Streaming_History_Audio_*.json` files in `data/spotify_history/`.
3. Run `uv run python scripts/setup.py` to import them automatically.

### Recent plays — Spotify API (Instant)

```bash
uv run python scripts/sync_api.py
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
        "command": "uv",
        "args": ["run", "python", "ABSOLUTE_PATH\\apps\\mcp\\server.py"],
        "cwd": "ABSOLUTE_PATH"
      }
    }
  }
  ```
  > **Note:** Replace `ABSOLUTE_PATH` with the full path to this project folder. Use `\\` for Windows.

3. Click `Developer > Reload MCP Configuration`. You should see `Spotify-Analytic` in the `+ > Connectors` menu.

<details>
<summary><i>If Claude Desktop cannot find the path:</i></summary>

If `uv` fails, use the path to the internal python interpreter:
```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "ABSOLUTE_PATH\\.venv\\Scripts\\python.exe",
      "args": ["ABSOLUTE_PATH\\apps\\mcp\\server.py"]
    }
  }
}
```
</details>

### Claude Code (CLI)

At project root run the command in terminal
```bash
claude mcp add spotify-analytics -- uv run python apps/mcp/server.py
```

Restart Claude Code after saving. Run the command to check if the MCP server is connected successfully.
```bash
claude mcp list
```

---

## Section 5 — Authentication

Once MCP server is connected, you can ask Claude to handle setup:

1. **Check status:** "Run `setup_check` to see what I'm missing."
2. **Run setup:** "Run `setup` for me."

Claude will initialize the database and open your browser for Spotify login. After you approve, tokens are saved locally. You only need to do this once.

*Alternatively, run from terminal:* `uv run python scripts/setup.py`

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
| `setup` | Run full setup: init DBs, auto-generate encryption key, connect Spotify via browser OAuth | No |
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
→ Check your `.env` file has `SPOTIFY_CLIENT_ID=...` (no quotes, no 
s around `=`)

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

**"Cannot find my `claude_desktop_config.json`"**
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

## Developer Debug

Run official MCP inspector (requires Node.js):
```bash
npx @modelcontextprotocol/inspector uv run python apps/mcp/server.py
```