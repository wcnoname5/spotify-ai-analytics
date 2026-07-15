# Project Overview

Personal Spotify analytics app. Target architecture (see `spotify-project-spec.md`):

- **Cloudflare D1** is the single source of truth (listening history + encrypted Spotify tokens)
- **Cloudflare Worker** (TypeScript, `worker/`) is the *only* thing that talks to D1 — Bearer-token gated
- **GitHub Actions cron** (hourly, Python) pulls recent plays from the Spotify API and writes them to D1 via the Worker
- **Local SQLite** is a pull-only sync cache of D1 (never written to independently); MCP and report generation read it

---

## Repo Layout

```
packages/core/        # spotify_core: db/ report/ spotify_client/ spotify_utils/
packages/dataloader/  # spotify_dataloader: Polars + Pydantic ingestion
apps/mcp/             # spotify_mcp: MCP server + Typer CLI
worker/               # Cloudflare Worker (TS) + D1 migrations
scripts/              # cron sync, local sync, one-off migration scripts
data/                 # Local SQLite DBs and JSON exports — never commit data/*.db
tests/                # Pytest suite (tests/core, tests/mcp)
```

---

## Coding Conventions

### Always
- Use `uv` for all Python dependency management (`uv add`, `uv sync`, `uv run`); Python >= 3.12
- Run `uv run pytest` before declaring any task done
- D1 is the source of truth; local SQLite is a cache — all D1 access goes through the Worker, never direct
- All Spotify API calls go through `packages/core/spotify_core/spotify_client/` only
- Encrypt tokens (Fernet) before they touch SQLite or the wire — the Worker/D1 only ever see ciphertext; decrypt only inside `spotify_client/`
- The D1 schema is generated from `spotify_core/db/schema.py` — never hand-author a second schema

### Never
- Commit `data/*.db` files or `.env` files
- Print track names or tokens in GitHub Actions logs (public repo) — row counts only
- Use `localhost` in OAuth redirect URIs — use `127.0.0.1` explicitly (Spotify banned localhost Nov 2025; PKCE flow is mandatory)

---

## Environment Variables

Check `.env.example`, tunables with defaults live in `spotify_core/config.py`.

---

## Common Commands

```bash
uv sync                                # install all Python dependencies
uv run pytest                          # run tests
uv run python apps/mcp/server.py      # run MCP server directly
uv run python scripts/sync.py         # cron sync: Spotify API -> D1 (needs WORKER_* env)
uv run python scripts/local_sync.py   # refresh local SQLite cache from D1
cd worker && npm test                  # Worker unit tests (vitest)
cd worker && npx wrangler deploy       # deploy the Worker
```
