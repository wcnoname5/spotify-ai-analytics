# Guide for Coding Agents

This file tells Coding Agents how to work in this repository.

---

## Project Overview

Spotify AI Analytics Agent. Combines:
- LangGraph agent for NLP queries over Spotify history
- MCP server for Claude Desktop/Code integration
- Plotly dashboard for streaming history visualization
- A LLM-based report analysis generation block based on the listening data

**Current phase: Phase 1 — building MCP server.**

---

## Repo Layout

```
packages/core/        # Shared Python packages (analytics, agent, memory, db, spotify_client)
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server entry point
apps/web/             # Web app (dashboard and report generation)
data/                 # Local SQLite DBs and JSON exports — never commit data/*.db
tests/                # Pytest suite
```

---

## Development Rules

### Always
- Use `uv` for all dependency management (`uv add`, `uv sync`, `uv run`)
- Run `uv run pytest` before declaring any task done
- Keep `packages/core/analytics/` and `packages/dataloader/` as pure functions — no side effects, no I/O
- All Spotify API calls go through `packages/core/spotify_client/` only — never call `httpx`/`requests` to Spotify directly from other modules
- Encrypt tokens before writing to SQLite — never store plaintext access/refresh tokens

### Never
- Commit `data/*.db` files or `.env` files
- Add `print()` debugging — use `logging` module
- Break existing Streamlit app functionality (it lives in `apps/web/ui/` and must stay runnable)
- Use `LangMem` for synchronous memory retrieval (59s p95 latency — use `SqliteStore` directly)
- Use `localhost` in OAuth redirect URIs — Spotify banned this Nov 2025, use `127.0.0.1` explicitly

### Imports
- `packages/core` modules import from each other via package names (uv workspace)
- `apps/mcp/` imports from `packages/core` only — no direct Spotify API calls
- `apps/web/` imports from `packages/core` only

---

## OAuth Rules

- Flow: Authorization Code with PKCE (mandatory — Spotify deprecated Implicit Grant Nov 2025)
- Redirect URI: always `http://127.0.0.1:{port}/callback` — never `localhost`
- Tokens: encrypt before storing in SQLite, decrypt only in `spotify_client/` module

---

## MCP Server Conventions

- Each MCP tool function must have a clear docstring (Claude uses it as tool description)
- Tools should be stateless wrappers — all state lives in `packages/core`
- Return structured dicts, not raw strings, where possible
- Tool names: `snake_case`, descriptive (`sync_history` not `sync`)

---

## Testing

```bash
uv run pytest                          # run all tests
uv run pytest tests/test_analytics.py  # run specific module
uv run pytest -k "test_memory"         # run by keyword
```

- Unit tests for `analytics/` and `dataloader/`: mock filesystem, no real Spotify calls
- Integration tests for `spotify_client/`: use `pytest-recording` or mock responses
- MCP tools: test tool logic separately from MCP transport layer

---

## Environment Variables

```bash
# Required for MCP and web both
SPOTIFY_CLIENT_ID=
TOKEN_ENCRYPT_KEY=    # Fernet key for token encryption

# Required for web only
GEMINI_API_KEY=       # or OPENAI_API_KEY

# Optional
LOG_LEVEL=INFO        # DEBUG for verbose output
```

Copy `.env.example` → `.env`. Never commit `.env`.

---

## Common Commands

```bash
uv sync                                    # install all dependencies
uv run python apps/mcp/server.py           # run MCP server directly
uv run streamlit run apps/web/ui/main_page.py  # run web UI (Phase 2)
uv run uvicorn apps.web.api.main:app --reload  # run FastAPI (Phase 2)
uv run pytest                              # run tests
uv add <package> --package core            # add dep to core package
uv add <package> --package mcp-app         # add dep to mcp app
```
