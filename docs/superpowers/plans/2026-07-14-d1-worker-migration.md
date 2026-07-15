# D1 + Worker API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the R2-blob-round-trip cron with a live Cloudflare D1 database behind a thin authenticated Worker, and rewrite the GH Actions cron + local sync path around it, per `docs/superpowers/specs/2026-07-14-d1-worker-migration-design.md`.

**Architecture:** One TypeScript Worker is the sole gateway to D1 (Bearer-gated, GET+POST for tracks/tokens/cursor). The GH Actions cron and a new local sync script talk to it via a small Python `WorkerClient`. Local SQLite is untouched for MCP/report reads — it's refreshed by pulling from the Worker instead of writing directly from Spotify API calls.

**Tech Stack:** Cloudflare Workers + D1 (`wrangler`), Python `httpx`, existing `spotify_core`/`pytest` stack.

## Global Constraints

- `uv` for all Python dependency management; Python >= 3.12; `uv run pytest` before declaring done.
- `spotify_core/db/queries.py` stays pure/no I/O — Worker HTTP calls go in a new `worker_client.py`, same split as `migrations.py` (I/O) vs `queries.py` (pure).
- Real Spotify API calls stay inside `spotify_client/` — the Worker is our own service, so `worker_client.py` living in `db/` doesn't violate this.
- Tokens are Fernet-encrypted before touching SQLite or the wire; the Worker/D1 only ever see ciphertext.
- Never commit `data/*.db` or `.env`. GH Actions logs are public — row counts only, never track names/tokens.
- Reuse `spotify_core/db/schema.py` DDL verbatim for D1 — no second schema.

---

### Task 1: Extract `parse_api_item` (pure) out of `pipeline.py`

Cron's Worker-based sync needs to turn a Spotify API item into a row dict without a local DB connection. Extract the pure parsing half of `_insert_item_from_api_response` (`packages/core/spotify_core/db/pipeline.py:153-197`) into `parse_api_item(item: dict, source: str = "api") -> dict | None`, returning the same fields the DB insert uses plus `played_at_ms`; have `_insert_item_from_api_response` call it. Add one test asserting a valid item parses correctly and a bad `played_at` returns `None`. Run `uv run pytest tests/core/test_pipeline.py`, commit.

### Task 2: Encrypted-row export/import in `token_store.py`

Add `export_encrypted_row(db_path, user_id) -> dict | None` and `import_encrypted_row(db_path, user_id, row: dict) -> None` to `packages/core/spotify_core/spotify_client/token_store.py` — raw passthrough of the `access_token/refresh_token/expires_at/scopes` columns, no encrypt/decrypt. These let the cron/migration scripts move ciphertext between D1 and a scratch local file. Add one round-trip test (export then import then `load_tokens` still decrypts correctly). Commit.

### Task 3: Worker scaffold — D1 migration, wrangler config, auth

Create `worker/` (package.json, tsconfig.json, wrangler.toml with a `DB` D1 binding + an `[env.test]` block). Generate `worker/migrations/0001_init.sql` from `spotify_core.db.schema.ALL_DDL` via a small new `scripts/gen_d1_migration.py` (run once now, rerun manually whenever schema.py changes — not part of CI). Implement `worker/src/auth.ts`: `requireAuth(request, env): Response | null`, checking `Authorization: Bearer <env.AUTH_TOKEN>`, returning 401 on mismatch. Use `@cloudflare/vitest-pool-workers` for a 3-case auth test (match / missing / wrong token). Commit.

### Task 4: Worker tracks endpoints

In `worker/src/tracks.ts`: `handleGetTracks` (`GET /api/tracks?since=<ms>` or `?from=&to=`, returns `{"tracks":[...]}`), `handlePostTracks` (`POST /api/tracks` body `{"tracks":[row,...]}`, `INSERT OR IGNORE` batch via `env.DB.batch`, returns `{"inserted": n}`), `handleGetTracksCount` (`GET /api/tracks/count` → `{"count": n}`). Wire routes into a new `worker/src/index.ts`. One test file covering insert+fetch, duplicate-id idempotency, and count. Commit.

### Task 5: Worker tokens + cursor endpoints

In `worker/src/tokens.ts`: `handleGetTokens`/`handlePostTokens` (`GET/POST /api/tokens?user_id=`, ciphertext passthrough, 404 if missing), `handleGetCursor`/`handlePostCursor` (`GET/POST /api/cursor`, reads/writes the `sync_state` row keyed `last_played_at_ms`, defaults to 0). Wire into `index.ts`. One test file covering the token round-trip, 404 case, and cursor default+advance. Commit.

### Task 6: Python `WorkerClient`

Create `packages/core/spotify_core/db/worker_client.py`: `WorkerClient(base_url, auth_token, http_client=None)` with `get_cursor`, `post_cursor`, `get_tokens`, `post_tokens`, `get_tracks_since`, `post_tracks` (returns inserted count), `get_tracks_count` — thin `httpx` wrappers sending the Bearer header, matching the Worker's JSON shapes from Tasks 4-5 exactly. Test with a `MagicMock` http client (same pattern as `tests/core/test_client.py`), one case per method. Commit.

### Task 7: `sync_api_to_worker` + rewrite `scripts/sync.py`

Add `sync_api_to_worker(tokens_scratch_db_path, user_id, client_id, worker: WorkerClient) -> dict` to `pipeline.py`: pull the encrypted token row from the Worker into a scratch local tokens DB (so unmodified `SpotifyClient`/`token_store` code can run), call `SpotifyClient.get_recently_played(after=worker.get_cursor())`, parse items via `parse_api_item`, `worker.post_tracks(...)` + `worker.post_cursor(...)` if advanced, then `worker.post_tokens(...)` with whatever `SpotifyClient` refreshed. Leave `sync_api_to_db`/`sync_api_up_to_date` untouched (still used by local/import flows). Rewrite `scripts/sync.py` to build a `WorkerClient` from `WORKER_URL`/`WORKER_AUTH_TOKEN` env vars and call this function inside a `tempfile.TemporaryDirectory()`. Test with mocked `WorkerClient` + mocked `SpotifyClient`, covering the happy path and the "no tokens" error. Run `uv run pytest tests/core -v`, commit.

Before merging, check `spotify_client/client.py`'s constructor: if it needs a real Fernet key even though the scratch DB only ever holds ciphertext it never decrypts itself, pass `settings.fernet_key_bytes` instead of `None`.

### Task 8: One-time R2 → D1 migration script

Create `scripts/migrate_r2_to_d1.py <history_db_path> <tokens_db_path>`: read all `listening_history` rows locally, `worker.post_tracks(...)` in batches of ~200, migrate the token row via `export_encrypted_row` + `worker.post_tokens(...)`, then assert `worker.get_tracks_count() >= local_count` (exit 1 with a warning if not). No automated test — it's a one-off real-data migration; the row-count assertion is its own verification. Commit.

### Task 9: Local incremental sync script

Add `init_meta_table(db_path)` to `migrations.py` (new local-only `meta` table, not part of the D1 schema). Create `packages/core/spotify_core/db/local_sync.py`: `run_local_sync(db_path, worker: WorkerClient) -> dict` — reads `last_sync_at_ms` from `meta`, calls `worker.get_tracks_since(...)`, upserts into local `listening_history`, updates `meta` to `worker.get_cursor()`. Thin CLI wrapper `scripts/local_sync.py`. Test the insert + idempotent-rerun cases with a mocked `WorkerClient`. Commit.

### Task 10: Rewrite `sync-test.yml`, validate on a branch

Rewrite `.github/workflows/sync-test.yml` (`workflow_dispatch` only): checkout, `uv sync`, Node setup, `npm ci` in `worker/`, `wrangler deploy --env test`, `wrangler d1 migrations apply spotify-analytics-test --remote`, run `scripts/sync.py` against `WORKER_TEST_URL`/`WORKER_TEST_AUTH_TOKEN` secrets, print the row count via `WorkerClient.get_tracks_count()`. Validate with `gh workflow run sync-test --ref <branch>` — this runs the branch's version of the file without merging, and leaves the existing hourly `sync.yml` untouched throughout. Commit once green.

(Requires a one-time manual setup outside this repo: `wrangler d1 create` for both prod and test databases, filling in `wrangler.toml`'s placeholder `database_id`s, and setting the `WORKER_TEST_URL`/`WORKER_TEST_AUTH_TOKEN`/`WORKER_URL`/`WORKER_AUTH_TOKEN` GitHub secrets — same manual-dashboard-step pattern as the original R2 setup in DEPLOY.md.)

### Task 11: Cutover

Only start once Task 10's `sync-test` run is green.

1. Run `scripts/migrate_r2_to_d1.py` once for real against production R2 data and production D1; confirm it exits 0.
2. Rewrite `.github/workflows/sync.yml`: same shape as the rewritten `sync-test.yml` but with `schedule: cron: "23 * * * *"` instead of test-only dispatch, pointed at production secrets, plus a final step exporting D1 (`wrangler d1 export --remote`) and uploading the dump to the existing R2 bucket as a backup (`R2_BACKUP_BUCKET` secret).
3. `git rm -r apps/mcp/spotify_mcp/dashboard scripts/build_dashboard.py` (and `site/` if it exists in the repo).
4. Drop all PyPI publish tooling: `git rm .github/workflows/publish.yaml` (tag-driven OIDC publish to TestPyPI/PyPI) and `git rm -r .claude/skills/release-to-pypi`. Check `scripts/bump.py` — if its only purpose was version-bumping for these PyPI releases (no other caller), remove it too; if anything else still calls it, leave it and note why in the commit message.
5. Replace `scripts/setup_cloud.sh`: it currently creates the R2 bucket, seeds `history.db`/`tokens.db` into it, creates the Pages project, and sets up Access — all obsolete. Rewrite it to instead: `wrangler d1 create` for the prod/test databases (idempotent, skip if they already exist), apply `worker/migrations/`, `wrangler deploy` the Worker, and write the GitHub secrets (`WORKER_URL`, `WORKER_AUTH_TOKEN`, `WORKER_TEST_URL`, `WORKER_TEST_AUTH_TOKEN`, `R2_BACKUP_BUCKET`, plus the existing `SPOTIFY_CLIENT_ID`/`TOKEN_ENCRYPT_KEY` reads) via `gh`. Drop the Pages/Access-wall logic entirely — same idempotent-rerun-is-safe pattern as today.
6. Run `uv run pytest` — delete any test that only exercised the removed dashboard/build script.
7. Trim `docs/DEPLOY.md` and `README.md`: remove the Pages/Access/R2-as-live-DB and `uvx`/PyPI install instructions; replace with the new Worker deploy + one-time migration steps, pointing at the rewritten `scripts/setup_cloud.sh`.
8. Commit.

## Self-Review Notes

- Every spec section has a task: D1 schema reuse (3), Worker gateway incl. the count endpoint (4-5), cron rewrite (7), local sync (9), one-time migration (8), R2-as-backup and deletions (11), branch-first validation via `sync-test.yml` (10).
- Deferred items (Vue/Tauri/ReAct frontend, AI report, MCP-on-D1) are untouched by every task above — matches the design doc's scope.
- Interface consistency: `WorkerClient`'s method names/shapes (6) are exactly what Tasks 7-9 call, and exactly what the Worker (4-5) returns.
- Flagged rather than guessed: Task 7 calls out the one open question (whether `SpotifyClient`'s constructor tolerates a `None` Fernet key) to check against the actual file before merging, instead of assuming.
