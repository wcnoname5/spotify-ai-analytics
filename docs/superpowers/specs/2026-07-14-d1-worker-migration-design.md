# D1 + Worker API Migration (spec steps 1-3)

Design for the first phase of the restructure described in `spotify-project-spec.md`
section 6, steps 1-3: Worker API + D1 schema, GH Actions cron writing to D1, and a
local incremental sync script. Frontend (Vue/Tauri/ReAct) and AI report changes are
explicitly out of scope — deferred to spec steps 4-8.

## Motivation

Current architecture stores `history.db`/`tokens.db` as blob files in Cloudflare R2;
GH Actions downloads them, runs `scripts/sync.py`, re-uploads, then rebuilds a static
dashboard site and deploys it to Cloudflare Pages. This works but:

- R2 only holds a file, not a live queryable DB — every access needs a full
  download/upload round trip.
- The static Pages dashboard (`build_dashboard.py`) is a stripped-down, fixed-window
  (7/30/90/all) subset of the local Streamlit dashboard's functionality.
- PyPI/`uvx` distribution of the whole toolkit is being dropped — the future local
  entry point is a Tauri app, not a `pip`-installed CLI.

This phase moves the source of truth to Cloudflare D1 (an always-on, queryable
SQLite-compatible store) behind a thin authenticated Worker, and rewrites the cron
and local sync paths around it. It deliberately does not touch the frontend beyond
deleting the now-obsolete static dashboard.

## Scope

In scope:
- D1 schema (reusing existing table definitions)
- Cloudflare Worker (TypeScript) as the sole D1 access point
- GH Actions cron rewrite to read/write via the Worker
- A local incremental sync script that populates local SQLite from the Worker
- One-time migration of the current (live, up-to-date) R2 `history.db`/`tokens.db`
  into D1
- R2 repurposed as a periodic D1 export/backup target

Out of scope (deferred to later spec steps):
- Vue/TypeScript dashboard, ReAct chat UI, Tauri packaging
- AI report generation changes
- MCP reading from D1 (MCP keeps reading local SQLite only, per existing project
  convention — no live network dependency for tool calls)

## Deletions

Removed outright, no shims or deprecation period:
- `apps/mcp/spotify_mcp/dashboard/` (Streamlit UI)
- `scripts/build_dashboard.py` and its `site/` output
- Cloudflare Pages deploy + Access app steps in `sync.yml` / `sync-test.yml`
- The R2 download/upload-as-live-DB round trip in `scripts/sync.py` /
  `scripts/setup_cloud.sh`
- All PyPI publish tooling and `uvx --from spotify-analytics-mcp ...` distribution
  paths (README, DEPLOY.md, the `release-to-pypi` skill's target)

R2 is not deleted — it's repurposed (see below).

## D1 schema

`packages/core/spotify_core/db/schema.py` already
defines the SQLite DDL for `listening_history` and `spotify_tokens`. D1 speaks
standard SQLite DDL, so these same `CREATE TABLE` statements become the D1 schema
verbatim — no second schema to author or keep in sync.

- `listening_history` — unchanged shape (track/artist/played_at/duration/etc.)
- `spotify_tokens` — stores an already-Fernet-encrypted blob. Encryption/decryption
  happens only in Python (`spotify_core/spotify_client`); the Worker and D1 never
  see plaintext tokens.

A new `worker/` directory holds `wrangler.toml` and a migrations folder that applies
these statements via `wrangler d1 migrations apply`.

## Worker API (TypeScript)

One Cloudflare Worker, gated by `Authorization: Bearer <AUTH_TOKEN>` (secret in
Worker env). It is the only thing that ever talks to D1 directly — no other
component (cron, local sync, future dashboard) queries D1 except through this
Worker. It contains no business logic beyond auth-check + SQL:

| Endpoint | Purpose |
|---|---|
| `GET /api/tracks?since=<ts>` | Incremental pull (local sync script) |
| `GET /api/tracks?from=&to=&filter=` | Aggregate/range query (future dashboard) |
| `POST /api/tracks` | Cron upserts a batch of new play rows |
| `GET /api/tokens` | Cron reads the current encrypted token blob (to check expiry) |
| `POST /api/tokens` | Cron writes back the rotated encrypted token blob |

## GH Actions cron rewrite (`sync.yml` + `scripts/sync.py`)

New hourly flow:

1. `GET /api/tokens` → decrypt locally → refresh via existing
   `spotify_core/spotify_client` if expired → re-encrypt → `POST /api/tokens`
2. Call Spotify API for recent plays (existing client code, unchanged)
3. `POST /api/tracks` to batch-upsert new rows into D1
4. New step: `wrangler d1 export` → upload the dump to the existing R2 bucket as
   `backup.sql` (overwrite in place — no versioning needed at personal scale)

Removed from the workflow: the old R2 download/upload-as-live-DB steps, the
`build_dashboard.py` call, and the Pages deploy step. `sync.yml` shrinks
significantly. `sync-test.yml` mirrors the same trimmed steps against a test
D1 database/bucket.

## Local incremental sync script

A new plain Python script (`scripts/local_sync.py` or a function in
`spotify_core`, run manually via `uv run` — no Typer wizard ceremony needed here):

1. Read `last_sync_at` from a `meta` table in local SQLite (local-only table, not
   present in D1)
2. `GET /api/tracks?since=last_sync_at` from the Worker
3. Upsert rows into local SQLite using the same `listening_history` schema, so
   `spotify_core/db/queries.py` and the report pipeline keep working unmodified —
   they read a cache now populated by pulling from D1 instead of by direct
   Spotify API writes
4. Update `last_sync_at`

MCP is unaffected: it continues to read local SQLite only, refreshed by this
script when the user wants current data.

## One-time R2 → D1 migration (run once, before cutover)

The current R2 bucket holds `history.db`/`tokens.db` that the live hourly cron
keeps up to date — this data must be seeded into D1 before switching over, not
recreated from scratch:

1. Download current `history.db` + `tokens.db` from R2 (existing script logic)
2. Read rows locally and `POST` them to the Worker's `/api/tracks` and
   `/api/tokens` endpoints in batches — same schema, so this is a straight row
   copy with no transform
3. Verify row counts match (local `SELECT COUNT(*)` vs. a D1 count query) before
   flipping `sync.yml` to the new flow
4. Old `history.db`/`tokens.db` in R2 can then be left in place or deleted; R2's
   ongoing role becomes the D1-export backup target described above, not these
   files

This is a manual/one-off script — it runs once during cutover, then is
deletable.

## Testing

- Worker: unit tests for the auth middleware (reject missing/wrong Bearer token)
  and each endpoint's SQL, run against a local D1 (`wrangler d1` local mode)
- `scripts/sync.py`: existing test patterns extended to mock the Worker HTTP
  calls instead of R2/file I/O
- Local sync script: unit test with a mocked Worker response, asserting
  `last_sync_at` advances and rows land in local SQLite
- Migration script: run once against the test D1 bucket during `sync-test.yml`
  dry-run, verify row-count assertion

## Rollout sequencing

The existing hourly `sync.yml` (R2-based, on `main`) and manual `sync-test.yml`
(any ref) are independent workflows — nothing about building or testing the D1
path touches `sync.yml`. `sync-test.yml` is already registered on `main`
(`workflow_dispatch`-only), so `gh workflow run sync-test --ref <branch>` runs
the *branch's* version of the file without merging anything — no need to land
changes on `main` to validate them.

Order of operations:

1. Build the Worker + D1 schema/migrations, write the one-time R2→D1 migration
   script (section above).
2. Rewrite `sync-test.yml` to exercise the new D1 flow (steps B-E). Dispatch it
   against the branch (`gh workflow run sync-test --ref <branch>`) and verify
   row counts and token round-tripping against a **test** D1 database. The
   current R2-based `sync.yml` keeps running hourly on `main`, untouched, the
   entire time — it remains the live data path and safety net until cutover.
3. Once `sync-test.yml` is consistently green: run the one-time R2→D1
   migration for real (production R2 bucket → production D1), verify row
   counts, then merge — swapping `sync.yml` itself over to the new D1 flow in
   the same change.

Cutover is a single deliberate step at the end, not a gradual migration —
`sync.yml` only changes once the new path has already been proven via
`sync-test.yml`.
