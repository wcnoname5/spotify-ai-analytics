# Report History Storage — Design

**Date:** 2026-07-18
**Status:** Approved for planning (branch `report-db`)
**Scope:** Persist generated AI reports with queryable metadata; retrieve them in the Tauri frontend and via MCP. Roadmap item 1 toward v0.1.

## Decisions (settled with user)

1. **Storage:** one `reports` table — text lives in the table (KB-scale markdown), **no R2, no .txt files**. D1 is the source of truth, same as listening history.
2. **Local-first write + push:** whoever saves writes the report row **locally first** (`synced=0`), then pushes to the Worker and marks `synced=1`. Failed pushes are retried by the next sync (outbox = the unsynced rows themselves; no separate queue table).
3. **Who saves:** terminal/MCP runs — the Python CLI (`python -m spotify_core.report`) saves by default (`--no-save` opts out). **Tauri saves explicitly:** it invokes the CLI with `--no-save` and persists only when the user clicks **"Save to DB"** (local insert `synced=0` + push, via the same sync machinery it already needs for startup push/pull).
4. **History UI:** a "Past reports" list on the existing Report page (date + style + model rows; click renders in the same viewer). No new nav entry.
5. **Invariant change (documented):** `history.db` is no longer 100% disposable — unsynced report rows are lost if the db is deleted before a sync. Synced state is always recoverable from D1.

## Schema (shared `db/sql/schema.sql` — single source of truth, both D1 and local)

```sql
CREATE TABLE IF NOT EXISTS reports (
    id             TEXT PRIMARY KEY,          -- uuid4, minted by the CLI; makes push idempotent
    style          TEXT NOT NULL,
    period_type    TEXT NOT NULL,             -- weekly | monthly | quarterly (UI's "seasonal" maps to quarterly; no custom)
    start_date     TEXT NOT NULL,             -- YYYY-MM-DD
    end_date       TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    generated_at   TEXT NOT NULL,             -- UTC ISO, minted by the CLI
    revision_count INTEGER NOT NULL DEFAULT 0, -- this is the one directly from langgraph
    report_text    TEXT NOT NULL,
    synced         INTEGER NOT NULL DEFAULT 0  -- meaningful locally only; D1 never reads it
);
CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON reports (generated_at);
```

One shared CREATE for both sides — an unused `synced` column in D1 is cheaper than divergent DDL. Worker gets a new migration file containing the same CREATE (copied from schema.sql, per the existing migration convention).

## Components

### 1. Worker (thaws the freeze for CRUD only — aggregation stays banned)
- `POST /api/reports` — body = one report row; `INSERT OR IGNORE` by `id`; existing Bearer auth.
- `GET /api/reports?since=<generated_at>` — rows with `generated_at > since`, ordered; same cursor shape as `/api/tracks`.

### 2. Shared SQL (`db/sql/`)
`insert_report.sql` (INSERT OR IGNORE, all columns + synced), `unsynced_reports.sql`, `mark_report_synced.sql`, `max_report_generated_at.sql` (cursor), `list_reports.sql` (metadata only, newest first), `get_report.sql` (by id, with text). Same `?N` conventions as the existing files. (Cursor note: `MAX(generated_at)` includes unsynced local rows — fine under the single-machine/single-writer assumption; `INSERT OR IGNORE` covers stragglers.)

### 3. Python
- `db/report_store.py` (or extend `local_sync.py` if it stays tiny): `save_report_local(...)`, `push_unsynced(worker_url, token)`, `pull_reports(...)` for `local_sync.py`'s full-cache refresh.
- `report/__main__.py`: after a successful generation — mint `id`/`generated_at`, `save_report_local`, attempt `push_unsynced`; **fail-soft on push** (warning on stderr, stdout contract unchanged: markdown only). New flag `--no-save` for throwaway runs (Tauri always passes it — see decision 3).
- LangSmith tracing needs env vars (`.env.example` updated) and wrapping on a compiled graph runtime.
    ```python
    import langsmith as ls

    with ls.tracing_context(enabled=True):
        graph.invoke(...)
    ```
- MCP: two read tools (`list_reports`, `get_report`) over the same queries.

### 4. Tauri
- **Step 0 (prep rename):** replace the `seasonal` period value with `quarterly` in TS (`lib/period.ts`, `ReportPage.vue`) so the stored `period_type` needs no mapping.
- `sync.ts` startup sync: push unsynced report rows (POST via the existing plugin-http path), then pull `?since=` cursor into local — mirrors the tracks flow.
- `queries.ts`: `listReports()` (metadata), `getReport(id)` (text).
- `ReportPage.vue`: "Past reports" list under the generator; click loads into the existing `report`/`caption` state (rendered by the same markdown pipeline). Saved reports appear at the top of the list.
    - After a report renders, two new buttons:
        - **"Save to DB"** — only on click is the report persisted (local insert `synced=0`, then push; button becomes "Saved" / disabled). Generation alone stores nothing.
        - **"Export .md"** — save-file dialog, writes the raw markdown to the chosen path. No DB involvement.
    - Before generating, `generate()` checks the local db for an existing report with the **same start_date + end_date**; if found, a confirm dialog warns before regenerating. A regenerate that gets saved is **just another new row** (new uuid) — it never replaces the old one; the list shows both, newest first.

## Error handling

- Push failure anywhere: row stays `synced=0`, retried next CLI run / next app startup; UI may show a small "N unsynced" note (console detail is enough for v1).
- Pull failure: existing offline-notice pattern; list renders from local cache.
- `INSERT OR IGNORE` + uuid id makes every push/pull idempotent; concurrent CLI + app sync is safe (WAL, same as tracks).
- **Concurrency with the cron (by construction, not by locking):** D1 is a single-writer SQLite — cron track-inserts and report POSTs serialize server-side; they share no rows and no cursor (`sync_state` is cron-only), so there is no read-modify-write to race. Discipline that keeps this true: report writes stay one `INSERT OR IGNORE` per statement — never a BEGIN/COMMIT batch (sqlx-pool hazard locally, cross-request ordering on D1).

## Testing

- Pytest: `report_store` round-trip (save local → unsynced list → mark synced), cursor query; push tested against a stubbed Worker (monkeypatched HTTP), not live.
- Worker: typecheck only (existing convention).
- TS: manual pass in `tauri dev` (generate → Save to DB → appears in list; generate without saving → nothing persisted; Export .md writes the file; restart → survives; delete db → resyncs from D1 minus unsynced).

## Explicitly deferred

- Search/filter over past reports, delete/retention, separate History page, report streaming.

- Refactor the multi-agent system by using langchain `create_agent()` instead of designing every workflow from scratch (more flexiable for memory and integrating more tools)