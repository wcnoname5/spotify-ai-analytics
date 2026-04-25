# Spotify AI Analytics Agent — Architecture Spec (v2)

> **Purpose**: Living spec for Claude Code sessions. Update this file as decisions are made.
> **Status**: Planning complete. Ready for implementation.
> **Phase**: Starting Phase 1 (MCP mode)

---

## 1. Project Goals & Constraints

### Target Users
- Primary: Personal use + friends (~25 users max)
- Spotify dev mode quota (25 allowlisted users) is sufficient — no need for extended quota

### Hard Constraints
- No dedicated 24/7 server budget
- Web deployment deferred: token privacy + LLM cost model unresolved
- LLM cost: MCP mode uses user's own Claude subscription ($0 extra cost)
- OAuth: **PKCE only** — Spotify deprecated Implicit Grant + HTTP redirects as of Nov 2025

### Phase Priority
1. **Phase 1 (NOW)**: Local MCP server — playback control + analytics tools + memory
2. **Phase 2 (LATER)**: Web app (FastAPI + Streamlit) — preserve existing functionality, add OAuth web flow

---

## 2. Repository Structure (Monorepo)

Single repo, `uv` workspace. MCP and Web share the same core packages.

```
spotify-ai-analytics/
│
├── packages/
│   ├── core/
│   │   ├── spotify_client/    # OAuth PKCE, token mgmt, Spotify API calls
│   │   ├── analytics/         # MIGRATED from src/analytics/ — minimal changes
│   │   ├── agent/             # MIGRATED from src/spotify_agent/ — add memory, playback tools
│   │   ├── memory/            # NEW: LangGraph SqliteSaver + SqliteStore
│   │   └── db/                # NEW: SQLite models (history, tokens, ltm)
│   └── dataloader/            # MIGRATED from src/dataloader/ — minimal changes
│
├── apps/
│   ├── mcp/                   # Phase 1
│   │   ├── server.py          # MCP server — wraps core/agent tools as MCP tools
│   │   ├── auth.py            # Local OAuth PKCE flow (127.0.0.1 callback)
│   │   └── README.md          # Setup instructions for Claude Desktop/Code
│   │
│   └── web/                   # Phase 2 (skeleton only for now)
│       ├── api/               # FastAPI: /auth/callback, /chat, /sync
│       └── ui/                # MIGRATED from src/app/ Streamlit pages
│
├── data/                      # Existing Spotify JSON exports (unchanged)
├── tests/                     # Shared test suite
├── pyproject.toml             # uv workspace root
└── CLAUDE.md                  # Instructions for Claude Code (this repo's AI guide)
```

### Migration Map (existing → new)

| Current path | New path | Change |
|---|---|---|
| `src/analytics/` | `packages/core/analytics/` | Move only |
| `src/dataloader/` | `packages/dataloader/` | Move only |
| `src/spotify_agent/` | `packages/core/agent/` | Move + add memory/playback tools |
| `src/app/` | `apps/web/ui/` | Move, keep functional for Phase 2 |
| _(new)_ | `packages/core/spotify_client/` | OAuth PKCE + API client |
| _(new)_ | `packages/core/memory/` | LangGraph persistence layer |
| _(new)_ | `packages/core/db/` | SQLite schema + models |
| _(new)_ | `apps/mcp/server.py` | MCP tool wrapper |

---

## 3. Tech Stack Decisions

### Confirmed

| Layer | Choice | Reason |
|---|---|---|
| Package manager | `uv` (already in use) | Keep consistent |
| Monorepo | `uv` workspace | No extra tooling needed |
| Local DB | SQLite | Zero infra, single-user, file-based |
| OAuth flow | PKCE + Authorization Code | Spotify mandates this as of Nov 2025 |
| MCP framework | `mcp` Python SDK | Official SDK |
| Agent framework | LangGraph (already in use) | Keep, add memory layer |
| Short-term memory | `SqliteSaver` (LangGraph checkpointer) | Per-session, per thread_id |
| Long-term memory | `SqliteStore` (LangGraph store) | Cross-session, per user_id namespace |
| Data processing | Polars (already in use) | Keep |
| Web UI (Phase 2) | Streamlit (already in use) | Avoid React rewrite |
| Web backend (Phase 2) | FastAPI | Handles OAuth callback cleanly |

### Deferred / Open

| Decision | Options | Notes |
|---|---|---|
| Web token storage | httpOnly encrypted cookie vs per-session re-auth | Resolve in Phase 2 |
| Web LLM key | User-provided vs server-side | Cost model unresolved |
| Web hosting | Render (free tier, $0–$7/mo) + Supabase free | Decide in Phase 2 |
| Web DB | Migrate SQLite → Postgres (Supabase) | Only if multi-user web needed |

---

## 4. Core Package Specs

### 4.1 `packages/core/spotify_client/`

Responsibilities:
- OAuth PKCE flow: generate code verifier/challenge, open browser, handle `127.0.0.1` callback
- Token storage: save access + refresh tokens to SQLite, encrypt at rest
- Auto-refresh: refresh token before any API call if expired
- Typed wrappers for all Spotify endpoints used by the agent

Key endpoints:
```
GET  /me                              # User profile
GET  /me/player/recently-played       # Sync history (max 50, cursor-paged)
GET  /me/top/{type}                   # Top tracks/artists
GET  /me/player/currently-playing     # Now playing
GET  /me/player/devices               # Active devices
PUT  /me/player/play                  # Play/resume  ← Premium required
PUT  /me/player/pause                 # Pause        ← Premium required
POST /me/player/next                  # Skip         ← Premium required
PUT  /me/player/volume                # Volume       ← Premium required
POST /me/player/queue                 # Add to queue ← Premium required
POST /users/{id}/playlists            # Create playlist
POST /playlists/{id}/tracks           # Add tracks
GET  /search                          # Search tracks/artists
```

OAuth scopes needed:
```
user-read-recently-played  user-top-read
user-read-playback-state   user-modify-playback-state
user-read-currently-playing
playlist-modify-public     playlist-modify-private
```

### 4.2 `packages/core/memory/`

Two separate persistence objects — **do not conflate these**:

```python
# Short-term: conversation history within a session
# Resets when thread_id changes (i.e. new conversation)
checkpointer = SqliteSaver.from_conn_string("data/checkpoints.db")

# Long-term: user preferences/facts across ALL sessions
# Persists regardless of thread_id
store = SqliteStore.from_conn_string("data/ltm.db")
```

LTM namespaces:
```python
("user:{user_id}", "preferences")    # genre, energy, era taste
("user:{user_id}", "history_facts")  # "400hrs jazz in 2023"
("user:{user_id}", "feedback")       # "disliked recommendation X"
```

- **Write**: agent extracts preferences after each turn, upserts to store
- **Read**: inject top-k relevant memories into system prompt at conversation start
- **Do NOT use LangMem** for sync retrieval — 59s p95 latency, unusable

### 4.3 `packages/core/agent/`

Extends existing LangGraph graph. New intent types:

```
existing: factual_query / insight_analysis / recommendation / other
new:      playback_control / playlist_create / sync_history
```

New tools (alongside existing analysis tools):
- `play_track(uri)` / `pause()` / `skip()` / `set_volume(pct)`
- `add_to_queue(uri)`
- `create_playlist(name, track_uris, description)`
- `sync_recent_history()` → fetch from API, merge into SQLite, deduplicate
- `get_now_playing()` → return current track + playback context

### 4.4 `packages/core/db/`

```sql
-- data/history.db
CREATE TABLE listening_history (
    id           TEXT PRIMARY KEY,   -- hash(track_id + played_at)
    track_id     TEXT NOT NULL,
    track_name   TEXT,
    artist_name  TEXT,
    album_name   TEXT,
    played_at    DATETIME NOT NULL,
    ms_played    INTEGER,
    source       TEXT DEFAULT 'api'  -- 'json_import' or 'api'
);

-- data/tokens.db
CREATE TABLE spotify_tokens (
    user_id       TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,     -- encrypted
    refresh_token TEXT NOT NULL,     -- encrypted
    expires_at    DATETIME NOT NULL,
    scopes        TEXT
);

-- data/checkpoints.db  → managed by SqliteSaver (do not touch manually)
-- data/ltm.db          → managed by SqliteStore  (do not touch manually)
```

---

## 5. MCP Server Spec (`apps/mcp/`)

### Exposed MCP Tools

| Tool name | Underlying module | Description |
|---|---|---|
| `spotify_auth` | spotify_client | OAuth PKCE: open browser, store token |
| `get_now_playing` | spotify_client | Current track + context |
| `play_pause` | spotify_client | Toggle playback |
| `skip_track` | spotify_client | Next track |
| `set_volume` | spotify_client | Volume 0–100 |
| `add_to_queue` | spotify_client | Add track URI to queue |
| `sync_history` | spotify_client + db | Fetch recent plays, merge into SQLite |
| `analyze_history` | analytics | Natural language query → analysis result |
| `get_top_tracks` | analytics + db | Top tracks for time range |
| `get_top_artists` | analytics + db | Top artists for time range |
| `create_ai_playlist` | agent + spotify_client | Generate playlist from taste profile |
| `remember_preference` | memory | Explicitly store user preference |
| `get_memory_summary` | memory | Return known preferences summary |

### User Setup Flow

```bash
# 1. Clone + install
git clone <repo> && cd spotify-ai-analytics
uv sync

# 2. Configure
cp .env.template .env
# Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env

# 3. Add to Claude Desktop config
#    macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
#    Windows: %APPDATA%\Claude\claude_desktop_config.json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "uv",
      "args": ["run", "python", "apps/mcp/server.py"],
      "cwd": "/path/to/spotify-ai-analytics"
    }
  }
}

# 4. First run: call spotify_auth tool in Claude to trigger browser OAuth
# 5. Token saved locally, auto-refreshed going forward
```

---

## 6. Phase 2 Web App Sketch (deferred)

```
FastAPI (/api)
├── GET  /auth/login       → redirect to Spotify OAuth
├── GET  /auth/callback    → exchange code, store token in encrypted session cookie
├── POST /chat             → forward to LangGraph agent
├── POST /sync             → trigger history sync
└── GET  /dashboard/data   → return analytics JSON for Plotly

Streamlit (/ui)  — mostly unchanged from current
├── Chatbot page           → calls /api/chat
├── Dashboard page         → calls /api/dashboard/data
└── Settings page          → OAuth login button
```

Token privacy: store Spotify tokens in httpOnly encrypted session cookie only — server never persists to DB. If cookie expires, user re-authenticates.

---

## 7. Build Phases

### Phase 1: MCP Mode (~5 weeks)

| Week | Deliverable |
|---|---|
| 1 | Monorepo restructure: move existing code, set up `uv` workspace, verify all imports work |
| 2 | `spotify_client`: OAuth PKCE flow, token storage, basic API wrappers |
| 3 | `db` schema + `memory` layer: SqliteSaver/SqliteStore wiring, history sync from API |
| 4 | Playback tools + new agent intents + MCP server skeleton |
| 5 | AI playlist generation + memory read/write + end-to-end test + user README |

### Phase 2: Web App (~4 weeks, when ready)

| Week | Deliverable |
|---|---|
| 1 | FastAPI app, OAuth callback, session management |
| 2 | Migrate Streamlit UI to `apps/web/ui/`, wire to FastAPI |
| 3 | Deploy: Render + Supabase (if needed) |
| 4 | Multi-user testing, token security review |

---

## 8. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Playback requires Spotify Premium | Detect at runtime, gracefully disable playback tools, show clear message |
| `recently-played` returns max 50 tracks | Sync on MCP startup + manual trigger; deduplicate by `played_at + track_id` |
| Spotify API rate limits (dev mode) | Cache track metadata; batch requests; exponential backoff on 429 |
| SQLite concurrency for web multi-user | Fine for Phase 1; migrate to Postgres in Phase 2 if needed |

---

## 9. Out of Scope

- Spotify Web Playback SDK (in-browser audio streaming)
- Real-time "now playing" polling in Streamlit
- Multi-user web with server-side LLM key (cost model unresolved)
- Extended quota / public launch (>25 users)
