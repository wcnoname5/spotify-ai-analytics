# Project Overview

Personal Spotify analytics app, shipped as a Windows installer. Other people are
meant to download it and point it at **their own** Cloudflare account, so the
packaged app must not assume `uv`, Python or Node exists on the machine.

Architecture (full version in `docs/ARCHITECTURE.md`):

- **Cloudflare D1** is the single source of truth (listening history + encrypted Spotify tokens)
- **Cloudflare Worker** (TypeScript, `worker/`) is the *only* thing that talks to D1 — Bearer-token gated
- **Worker cron** (hourly `scheduled()` handler in `worker/src/sync.ts`) pulls recent plays from the Spotify API into D1 directly
- **Local SQLite** is a pull-only sync cache of D1 (never written to independently); MCP and report generation read it
- **The desktop app owns setup** — config, OAuth, history import, deploy. Python is
  down to LangGraph report generation and the MCP server.

---

## Repo Layout

```
packages/core/        # spotify_core: db/ report/ spotify_client/ spotify_utils/
packages/shared-ts/   # TS imported by BOTH worker/ and apps/tauri/ (Fernet, PKCE, row ids, export parsing)
apps/mcp/             # spotify_mcp: MCP server + Typer CLI (diagnostics + cloud pull only)
apps/tauri/           # Tauri 2 desktop app (Vite + TS frontend, src-tauri/ Rust shell) — deps separate from worker/
worker/               # Cloudflare Worker (TS) — migrations live in packages/core, not here
data/                 # Local SQLite DBs and JSON exports — never commit data/*.db
tests/                # Pytest suite (tests/core, tests/mcp)
```

---

## Coding Conventions

### Always
- Use `uv` for all Python dependency management (`uv add`, `uv sync`, `uv run`); Python >= 3.12
- D1 is the source of truth; local SQLite is a cache — all D1 access goes through the Worker, never direct
- Encrypt tokens (Fernet) before they touch the wire — D1 only ever sees ciphertext
- **One implementation per cross-boundary rule.** The recurring bug in this repo's
  history is the same logic existing twice and drifting:
  - schema → `spotify_core/db/sql/migrations/*.sql` — the only DDL, applied to D1 and
    to the local cache alike; `schema.py` derives its DDL from them
  - analytics SQL → `spotify_core/db/sql/*.sql`, shared with the TS layer via `@sql`
  - Fernet, PKCE, `listening_history.id`, export parsing → `packages/shared-ts/`, shared with the Worker via the `@shared` alias
  - config read/write → `apps/tauri/src-tauri/src/config.rs` writes, `spotify_core/config_file.py` reads
- Use `127.0.0.1` in OAuth redirect URIs, never `localhost` (Spotify banned it Nov 2025; PKCE is mandatory)

### Never
- Commit `data/*.db`, `config.json` or `dev.config.json`
- Print track names or tokens in CI logs or the Setup page's log pane (public repo)
- Add a second writer for config, or a second copy of anything in the list above
- Reach `env!("CARGO_MANIFEST_DIR")` or `Command::new` from a code path a packaged
  user can take — both only work on the machine that built the binary

---

## Configuration

A flat JSON file. One resolution rule, and nothing looks at the cwd:

```
$SPOTIFY_CONFIG set  ->  that path            (dev: data lands in ./data beside it)
otherwise            ->  platformdirs config dir / config.json
```

See `config.example.json`. Tunables with defaults live in `spotify_core/config.py`.

Development: `$env:SPOTIFY_CONFIG="./dev.config.json"; npm run tauri dev` — a
checkout then cannot read or write the database a packaged install uses.

---

## Common Commands

```bash
uv sync                                # install all Python dependencies
uv run pytest                          # Python tests
uv run spotify-mcp doctor              # environment readiness
uv run spotify-mcp cloud pull          # refresh local SQLite cache from D1
cd apps/tauri && npm test              # vitest: packages/shared-ts + frontend
cd apps/tauri && npm run tauri dev     # run the app
cd apps/tauri/src-tauri && cargo test  # Rust unit tests
cd worker && npm run typecheck         # Worker typecheck (no unit tests by choice)
```

Deploying the Worker is the app's job (Setup → Cloud sync → Deploy), not a CLI's.
`spotify-mcp cloud deploy` still exists but is broken — it looks for a
`worker/migrations/` directory that no longer exists.

---

## Documentation

Three files are maintained. Everything else in `docs/` was deleted for lying.

| | |
|---|---|
| `README.md` | For users. Changes only when user-visible behaviour does |
| `docs/ARCHITECTURE.md` | Boundaries, invariants, and why. **Read before changing anything** |
| `CLAUDE.md` | This file — conventions |


These rules keep them true, because 9 of the 10 files previously in `docs/` had rotted:

- **Docs follow architecture changes, not features.** Most commits need no doc change
  at all: the commit message is the record.
   When a change makes ARCHITECTURE.md *false* (e.g., a boundary moved, an invariant changed), fix it in the **same commit**. The test is one question: "is the old text now wrong?"

- **Minimal Architechure Edit**: Before making such invariant changes in , keep *YANGI* in your mind. Only when the decision is very important to furtue development when you write it down in documentation.

- **Prefer a test to a doc line.** An invariant with a test is enforced; the prose then
  only has to explain why the test exists. When adding an invariant, try to make it a test first.
