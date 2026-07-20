# Tauri Setup GUI (migrate one-time setup from wizard + setup_cloud.sh) — Draft

**Date:** 2026-07-18
**Status:** Draft / parked — not scheduled
**Scope:** Move the one-time setup flows (`apps/mcp/spotify_mcp/wizard/` CLI wizard and `scripts/setup_cloud.sh`) behind a Tauri setup GUI.

## Core principle

The GUI is a **front-end over the existing Python steps spawned as processes** — the pattern proven by `generate_report` (Rust spawns `uv run python -m ...`, reads stdout). Never reimplement OAuth/Fernet/Polars ingestion in Rust/TS: a third token-handling component would violate the project rule "decrypt only inside `spotify_client/` and the Worker cron", and duplicating step logic means the CLI wizard and GUI drift. Both front-ends drive the same Python step functions.

## Step inventory → migration disposition

| Today | In the GUI | Effort |
|---|---|---|
| `spotify_app.py` — app-registration guidance, port 8888 probe | Instructions card + "open dashboard" button (opener plugin) + Client ID input | Trivial |
| `credentials.py` — persist client ID, generate Fernet key | Form → `.env`; keygen via spawned python one-liner (crypto stays in Python) | Small |
| `llm_keys.py` / `langfuse_keys.py` | One form, 4 optional fields → `.env` | Trivial |
| `oauth_step.py` — PKCE, 127.0.0.1:8888 callback, encrypt+store | Button → spawn a **promptless** entry (`spotify-mcp oauth`); browser opens, Python runs the callback server, GUI polls exit | Medium |
| `history_import.py` — tkinter picker + Polars ingest | Tauri dialog plugin → spawn existing `spotify-mcp import-history --from <path>` (already non-interactive) | Small |
| `claude_desktop.py` — Claude Desktop config merge | **Not migrated** — serves MCP users, stays CLI-only | None |
| `state.py` — resumability checks | `spotify-mcp doctor --json` (new flag) drives the GUI's done/pending step list | Small |
| `setup_cloud.sh` [1–3b] — wrangler login/create/migrate/deploy/secrets | Spawn `npx wrangler ...`, stream output to a log panel; login still bounces to browser. Keep the Python wrangler.toml patcher, spawn it | Hard |
| `setup_cloud.sh` [4] — gh Actions secrets | **Not migrated** — Actions sync is manual-fallback only; stays in the script | None |
| `setup_cloud.sh` [5] — seed D1 | Spawn `uv run python scripts/seed_d1.py` with retry | Small |

## The two real architectural changes

1. **Build-time config → runtime config (prerequisite).** `WORKER_URL` / `WORKER_AUTH_TOKEN` / `HISTORY_DB_PATH` are currently baked into the JS bundle via Vite `define`. A GUI that writes `.env` is useless if the app can't re-read it without a rebuild. Add Rust `get_config` / `set_config` commands (read/write root `.env`, or OS keychain) and drop the `define` constants from the frontend. Side benefit: kills the "token inlined in the dev bundle" debt.
2. **Promptless entry points for wizard steps.** Step logic is already mostly separated from the rich-console prompts (`persist_client_id(raw)`, `import-history --from`); expose the rest (OAuth run, doctor-as-JSON) as non-interactive CLI subcommands — **all under the single `spotify-mcp` CLI**, so the later PyInstaller step (roadmap item 3) bundles exactly one exe. The interactive `spotify-mcp setup` wizard remains for MCP users — same step functions, two front-ends, zero duplicated logic.

## What does not change

Token flow (ciphertext in D1; decrypt only in `spotify_client/` / Worker), schema generation pipeline, the Worker itself, the CLI wizard as the MCP-side setup path.

## Phasing

- **Phase 0 (prereq):** runtime config commands (absorbed the old packaging-hardening keychain item).
- **Phase 1:** first-run Setup page — doctor state list, client-ID + LLM/Langfuse forms, Fernet keygen. Covers 5 of 8 wizard steps, all easy. First-run detection: no client ID configured → land on Setup.
- **Phase 2:** OAuth button + history import (the two spawned flows).
- **Phase 3 (optional, last):** cloud-setup orchestration. Runs once per lifetime — the most work for the least-used screen. Acceptable lazy landing point: a "prerequisites check (node/uv/gh) + open docs + paste WORKER_URL / token" screen, keeping `setup_cloud.sh` for the heavy lifting.

## Open questions (resolve at brainstorm time)

- Streaming: long steps (deploy, import) want live log lines → Tauri events instead of the current buffered spawn; decide per step.
- Where secrets land: `.env` (status quo) vs OS keychain — Phase 0 should pick once for both.
- Packaged-app story: all spawns assume repo checkout + uv; the PyInstaller sidecar decision (roadmap item 3) gates shipping any of this outside dev mode.
