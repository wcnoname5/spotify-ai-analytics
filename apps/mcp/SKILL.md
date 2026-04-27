# Spotify AI Analytics — Claude Skill

> Add the contents of this file to your project's CLAUDE.md (or paste it into Claude Desktop's system prompt field) so Claude knows how to use this MCP server effectively.

---

## What this MCP server provides

You are connected to a local Spotify AI Analytics MCP server with these capabilities:
- **History analytics** — query local SQLite DB of listening history (no auth needed)
- **Playback control** — control Spotify (requires auth + Spotify Premium)
- **Long-term memory** — store and retrieve user preferences across conversations

---

## First interaction with a new user

When the user first mentions Spotify or seems to be setting up the server:

1. Call `setup_check()` immediately.
2. Read the `actions_needed` list. Walk the user through each item in order — do not skip ahead.
3. After the user completes an action, call `setup_check()` again to confirm before moving on.
4. Once `ready: true`, confirm the server is fully configured and offer to show their listening stats.

---

## When analytics tools return a warning (empty DB)

If `get_listening_summary`, `get_top_artists`, or `get_top_tracks` return a dict with a `warning` field:

1. Tell the user: "Your local listening history database is empty."
2. Ask: "Have you already downloaded your Spotify data from https://www.spotify.com/account/privacy/?"
   - **If yes:** Guide them to run `uv run python scripts/import_json.py --dir data/spotify_history`
   - **If no:** Explain that requesting the JSON export takes a few days. In the meantime, they can sync recent plays: `uv run python scripts/sync_api.py --user-id <their_user_id>` (last 50 tracks only).
3. After they run one of these, call the analytics tool again to confirm data loaded.

---

## When a tool returns `requires_auth: true`

The user's Spotify OAuth tokens are missing or expired. Guide them to:
```bash
uv run python scripts/init_db.py --auth --user-id <their_user_id>
```
This opens a browser tab. They approve access, browser shows "Authentication complete", done. Tokens are saved and auto-refresh going forward.

---

## Tool selection guide

| User says… | Use this tool |
|------------|---------------|
| "What's playing?" / "Now playing?" | `get_now_playing` |
| "Play [track]" / "Resume" | `play_track` (need URI first — ask or search) |
| "Pause" / "Stop" | `pause_playback` |
| "Skip" / "Next song" | `skip_track` |
| "Volume up/down" / "Set volume to X" | `set_volume` |
| "Add to queue" | `add_to_queue` |
| "Top artists" / "Most played artists" | `get_top_artists` |
| "Top tracks" / "Most played songs" | `get_top_tracks` |
| "How much have I listened?" / "Overview" | `get_listening_summary` |
| "Sync my plays" / "Update history" | `sync_history` |
| "Remember that I like X" / "Note that…" | `remember_preference` |
| "What do you know about my taste?" | `get_memory_summary` |
| "Create a playlist" | `create_playlist` (generate URIs from analytics first) |
| "Is everything set up?" / "Something isn't working" | `setup_check` |

---

## Date range filtering

`get_top_artists` and `get_top_tracks` accept `start_date` and `end_date` in `"YYYY-MM-DD"` format.

Examples:
- "Last year" → `start_date="2024-01-01"`, `end_date="2024-12-31"`
- "This month" → compute from today's date
- "2023" → `start_date="2023-01-01"`, `end_date="2023-12-31"`

---

## Timestamps

`get_listening_summary` returns `earliest_played_at` and `latest_played_at` in the user's **local timezone** ISO format. Display them as-is — no further conversion needed.

---

## Playback tool limitations

- All playback tools (`play_track`, `pause_playback`, `skip_track`, `set_volume`, `add_to_queue`) require **Spotify Premium**.
- If they return `{"error": "Spotify Premium required for playback control."}`, tell the user Premium is required — do not retry.
- Track URIs follow the format `spotify:track:<22-char-id>`. You can get them from the analytics tools' `track_id` field or by asking the user to copy from Spotify.
