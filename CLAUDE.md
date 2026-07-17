# Project Overview

Personal Spotify analytics app. Target architecture (see `spotify-project-spec.md`):

- **Cloudflare D1** is the single source of truth (listening history + encrypted Spotify tokens)
- **Cloudflare Worker** (TypeScript, `worker/`) is the *only* thing that talks to D1 — Bearer-token gated
- **Worker cron** (hourly `scheduled()` handler in `worker/src/sync.ts`) pulls recent plays from the Spotify API into D1 directly; the old GitHub Actions workflow remains as a `workflow_dispatch` manual fallback only
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
- Encrypt tokens (Fernet) before they touch SQLite or the wire — D1 only ever sees ciphertext; decrypt only inside `spotify_client/` (Python: reauth wizard/MCP) and the Worker cron sync (`worker/src/fernet.ts` + `sync.ts`)
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
uv run python scripts/sync.py         # manual-fallback sync: Spotify API -> D1 (needs WORKER_* env); hourly cron runs in the Worker
uv run python scripts/local_sync.py   # refresh local SQLite cache from D1
cd worker && npm run typecheck         # Worker typecheck (no unit tests by choice)
cd worker && npx wrangler deploy       # deploy the Worker
```
