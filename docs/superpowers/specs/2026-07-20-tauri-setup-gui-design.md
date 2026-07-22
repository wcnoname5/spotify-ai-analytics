# Tauri Setup GUI — Design

**Date:** 2026-07-20
**Status:** Done (see commit `0d84b9`)
**Roadmap:** section 2, "One-time setup → Tauri GUI"

## Core principle

The GUI is a **front-end over the existing Python steps, spawned as processes** — the pattern already proven by `generate_report` (Rust spawns `uv run python -m ...`, reads stdout). OAuth, Fernet, and Polars ingestion are never reimplemented in Rust or TS: a third token-handling component would violate the project rule *decrypt only inside `spotify_client/` and the Worker cron*, and duplicating step logic guarantees the CLI wizard and the GUI drift apart.

The wizard steps are already split into logic and interactive shell:

```python
persist_client_id(raw)      # pure logic: validate + write. No prompts.
prompt_client_id(console)   # interactive shell: asks, warns, then calls the above.
```

The CLI wizard drives `prompt_*`. **The GUI never touches `prompt_*`** — it spawns promptless subcommands that call the same `persist_*` logic. One implementation, two front-ends.

## What already exists (scope shrank on inspection)

Verified in the codebase before writing this spec:

| Assumed new work | Reality |
|---|---|
| Path resolution / twin-`.env` fix | **Done.** `paths.py:30-49` resolves config/data dirs by `SPOTIFY_MCP_*` override → `DEV=true` → platformdirs. Dev keeps the repo-root `.env`; a packaged `.exe` has no `DEV`, so it lands on platformdirs automatically. No branch needed. |
| `.env` merge-write | **Done.** `env_file.upsert()` replaces in place, appends new keys, chmods 0600 off-Windows. |
| `doctor --json` | `doctor` already emits JSON via `console.print_json`. Needs a plain-output flag only. |
| `path --json` | `path` already emits JSON, but then prints rich-markup warnings that break machine parsing. Needs a flag to suppress them. |
| Promptless OAuth entry | **Done.** `run_oauth(console, force)` only prints, never reads input — so the existing `spotify-mcp reauth` *is* the promptless entry. No new `oauth` command. |
| Promptless history import | **Done.** `spotify-mcp import-history --from <path>` is already non-interactive. |

Net new CLI surface is three items: `path --json`, `doctor --json`, `config set K=V`.

## Phase 0 — runtime config (prerequisite)

`WORKER_URL` / `WORKER_AUTH_TOKEN` / `HISTORY_DB_PATH` are currently baked into the JS bundle by Vite `define` (`vite.config.ts:49-56`). A GUI that writes `.env` is useless if the app cannot re-read it without a rebuild. Removing the `define` block also kills the "auth token inlined in the dev bundle" debt.

**Reads are Rust, writes are Python.** Parsing a `.env` is trivial and Rust can do it; merge-*writing* one is the part with real failure modes (clobbering unsent fields, quoting, permissions), and that code already exists and is in use. Rust reimplementing it would be exactly the duplication this design avoids.

```
startup   Rust spawns `spotify-mcp path --json`
          -> {env_file, data_dir, dev}, cached for the session

get_config()        Rust parses that .env  -> {k: v}
set_config(patch)   Rust spawns `spotify-mcp config set K=V` (per key)
                    -> env_file.upsert()
```

Path-resolution logic therefore lives in exactly one place (`paths.py`), and `.env` write logic in exactly one place (`env_file.upsert`).

Frontend change: delete the three `define` constants; `db.ts` and `sync.ts` `await get_config()` at startup instead of reading build-time globals.

**Settings take effect on restart.** After `set_config` the UI shows "Saved — restart to apply". Settings change a handful of times per lifetime; hot-reload would mean tearing down the DB connection and rebuilding the sync client mid-flight, with in-flight queries to reason about. A first-time user restarts once anyway.

## Phase 1 — Setup page

A third page alongside the dashboard and `ReportPage.vue`, reached from the existing menu nav — not a separate window. Settings must remain reachable later (rotate an LLM key, re-run OAuth), and a second window would add window lifecycle and cross-window state sync for nothing.

**First-run detection:** no `SPOTIFY_CLIENT_ID` configured → land on Setup instead of the dashboard.

`doctor --json` drives a step list showing done/pending per step. Forms write via `set_config`:

- Spotify Client ID (+ link to the developer dashboard via the opener plugin)
- LLM keys, Langfuse keys, **LangSmith keys** (roadmap item; also add to `.env.example`)
- Fernet key generation — spawned, because crypto stays in Python; never regenerates over an existing key (`ensure_fernet_key` already guards this — regenerating orphans stored tokens)

**Gotcha to encode:** `doctor` exits **1** when the environment is not ready. During setup that is the normal state, so the Rust side must read the JSON and ignore the exit code — treating non-zero as a spawn failure would make every incomplete setup look like a crash.

## Phase 2 — the two spawned flows

- **OAuth** — button spawns `spotify-mcp reauth`. Python opens the browser and runs the `127.0.0.1:8888` callback server itself; the GUI waits for exit. (`127.0.0.1`, never `localhost` — Spotify banned it Nov 2025.)
- **History import** — Tauri dialog plugin picks the file, then spawns `spotify-mcp import-history --from <path>`.

**Output handling: buffered, with per-step status.** Identical to `generate_report` today: spawn, wait, collect stdout in one string. Each step renders `running | done | failed`; on failure the full stdout/stderr expands in a `<details>`. Streaming was considered and rejected for this scope — neither flow has meaningful intermediate progress to report, and a log-line event channel plus a LogPanel component is infrastructure bought for no gain. If Phase 3 is ever built, streaming gets reconsidered there on its own merits.

## Phase 3 — cloud setup (specified, not implemented)

The GUI does the cheap half only: check that `node` / `uv` / `gh` exist, open the deploy docs, and accept pasted `WORKER_URL` + auth token. `scripts/setup_cloud.sh` keeps the wrangler login/create/migrate/deploy/secrets work.

This runs once per user per lifetime — the most work for the least-used screen, and it cannot be tested without a real Cloudflare account and a real deploy. It is documented here so Phase 0–2's spawn interface is designed with it in mind, not so it gets built now.

## Not migrated, deliberately

- `claude_desktop.py` — Claude Desktop config merge serves MCP users; stays CLI-only.
- `setup_cloud.sh` step 4 (`gh` Actions secrets) — Actions sync is a manual fallback only.
- The interactive `spotify-mcp setup` wizard — remains the MCP-side setup path, sharing every step function with the GUI.

## Unchanged

Token flow (ciphertext in D1, decrypt only in `spotify_client/` and the Worker), the schema pipeline (`db/sql/schema.sql`), and the Worker itself.

## Verification

Phase 0 carries the only non-trivial new logic, and both halves of it are thin wrappers over tested code. One check: `config set K=V` writes through to `env_file.upsert` without disturbing sibling keys — write a key, read the file back, confirm the pre-existing keys survive.

The rest is UI over existing, already-tested subcommands; `uv run pytest`, `npm run typecheck`, and a manual first-run pass cover it.

## Packaging note

Every spawn assumes a repo checkout plus `uv`. Shipping this outside dev mode is gated on the PyInstaller sidecar decision (roadmap item 3) — which is also why the new CLI surface stays under the single `spotify-mcp` entry point, so packaging bundles exactly one executable.
