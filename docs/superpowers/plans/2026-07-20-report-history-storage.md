# Report History Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD not required — implement, then run the listed verify commands.

**Goal:** Persist generated AI reports in a `reports` table (local SQLite outbox → D1 via Worker), with Save-to-DB / Export-.md buttons and a Past-reports list in Tauri, plus MCP read tools.

**Architecture:** Local-first write with `synced=0`, idempotent push (`INSERT OR IGNORE` by uuid `id`) to a new Worker CRUD endpoint, cursor pull on `generated_at` — mirroring the existing tracks sync. Spec: `docs/superpowers/specs/2026-07-18-report-db-design.md`.

## Global Constraints

- Schema single source of truth: `packages/core/spotify_core/db/sql/schema.sql` (loaded by `schema.py`, imported raw by Tauri). Worker migration = copied CREATE; never touch applied `0001_init.sql` or rerun `gen_d1_migration.py`.
- All D1 access via the Worker (Bearer auth). Report writes: one `INSERT OR IGNORE` per statement, never BEGIN/COMMIT batches.
- CLI stdout contract: markdown only; push failures = stderr warning, never fatal.
- `period_type` values: `weekly | monthly | quarterly` (no `custom`/`seasonal`).
- Verify commands: `uv run pytest` · `cd worker && npm run typecheck` · `cd apps/tauri && npm run build` · `cargo check` in `src-tauri`.

---

### Task 1: Schema + shared SQL + D1 migration

**Files:** modify `packages/core/spotify_core/db/sql/schema.sql` (append); create 7 files in `packages/core/spotify_core/db/sql/`; create `worker/migrations/0002_reports.sql`.

- [ ] Append to `schema.sql` (auto-picked-up by `schema.py`/`init_db` and Tauri's `getDb()` — no loader changes):

```sql
CREATE TABLE IF NOT EXISTS reports (
    id             TEXT PRIMARY KEY,           -- uuid4, minted by whoever saves; makes push idempotent
    style          TEXT NOT NULL,
    period_type    TEXT NOT NULL,              -- weekly | monthly | quarterly
    start_date     TEXT NOT NULL,              -- YYYY-MM-DD
    end_date       TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    generated_at   TEXT NOT NULL,              -- UTC ISO
    revision_count INTEGER NOT NULL DEFAULT 0,
    report_text    TEXT NOT NULL,
    synced         INTEGER NOT NULL DEFAULT 0  -- meaningful locally only; D1 never reads it
);

CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON reports(generated_at);
```

- [ ] Create the SQL files (column order everywhere: `id, style, period_type, start_date, end_date, provider, model, generated_at, revision_count, report_text[, synced]`):

`insert_report.sql`:
```sql
INSERT OR IGNORE INTO reports
    (id, style, period_type, start_date, end_date,
     provider, model, generated_at, revision_count, report_text, synced)
VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
```
`unsynced_reports.sql`:
```sql
SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count, report_text
FROM reports WHERE synced = 0 ORDER BY generated_at
```
`mark_report_synced.sql`: `UPDATE reports SET synced = 1 WHERE id = ?1`
`max_report_generated_at.sql`: `SELECT MAX(generated_at) AS c FROM reports`
`list_reports.sql`:
```sql
SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count
FROM reports ORDER BY generated_at DESC
```
`get_report.sql`:
```sql
SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count, report_text, synced
FROM reports WHERE id = ?1
```
`count_reports_for_period.sql` (dup check = same start+end only):
```sql
SELECT COUNT(*) AS c FROM reports WHERE start_date = ?1 AND end_date = ?2
```

- [ ] `worker/migrations/0002_reports.sql` = the schema.sql block above, prefixed `-- Copied from packages/core/spotify_core/db/sql/schema.sql (reports table).`
- [ ] Verify: `uv run pytest tests/core/test_db.py -v` still green. Commit: `feat: reports table schema + shared SQL + D1 migration`

---

### Task 2: Python — report_store, WorkerClient, local_sync, CLI

**Files:** create `packages/core/spotify_core/db/report_store.py`; modify `worker_client.py`, `local_sync.py`, `report/__main__.py`, `report/graph.py`; create `tests/core/test_report_store.py`.

**Interfaces produced:** `REPORT_COLUMNS` (10 data columns, insert order); `save_report_local(db_path, row, synced=0)`; `push_unsynced(db_path, worker) -> int`; `pull_reports(db_path, worker) -> int` (stores `synced=1`); `list_reports(db_path) -> list[dict]`; `get_report(db_path, id) -> dict | None`; `WorkerClient.post_report(row) -> int` / `.get_reports_since(iso) -> list[dict]`.

- [ ] `worker_client.py` — append (same section-comment style as Tracks):

```python
    def post_report(self, row: dict) -> int:
        """Insert one report row (idempotent by id); return rows inserted (0 or 1)."""
        return self._request("POST", "/api/reports", json=row).json()["inserted"]

    def get_reports_since(self, since_iso: str) -> list[dict]:
        """Return report rows with generated_at strictly after since_iso."""
        return self._request("GET", "/api/reports", params={"since": since_iso}).json()["reports"]
```

- [ ] Create `report_store.py`:

```python
"""Local-first report persistence: save with synced=0, push to the Worker,
pull D1 rows behind a generated_at cursor. Outbox = the unsynced rows
themselves; INSERT OR IGNORE + uuid ids make every direction idempotent."""
from pathlib import Path
from typing import Optional, Union

from loguru import logger

from .local_sync import _EPOCH_ISO, _sql
from .migrations import get_connection, init_history_db
from .worker_client import WorkerClient

REPORT_COLUMNS = (
    "id", "style", "period_type", "start_date", "end_date",
    "provider", "model", "generated_at", "revision_count", "report_text",
)


def save_report_local(db_path: Union[str, Path], row: dict, synced: int = 0) -> None:
    """INSERT OR IGNORE one report row into the local db."""
    init_history_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(_sql("insert_report"),
                         tuple(row[c] for c in REPORT_COLUMNS) + (synced,))
    finally:
        conn.close()


def push_unsynced(db_path: Union[str, Path], worker: WorkerClient) -> int:
    """POST every synced=0 row to the Worker; mark each synced on success."""
    conn = get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(_sql("unsynced_reports")).fetchall()]
        for row in rows:
            worker.post_report(row)
            with conn:
                conn.execute(_sql("mark_report_synced"), (row["id"],))
        if rows:
            logger.info("Pushed {} report(s) to Worker", len(rows))
        return len(rows)
    finally:
        conn.close()


def pull_reports(db_path: Union[str, Path], worker: WorkerClient) -> int:
    """Pull D1 report rows newer than the local cursor; store them synced=1."""
    init_history_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(_sql("max_report_generated_at")).fetchone()["c"] or _EPOCH_ISO
            inserted = 0
            for row in worker.get_reports_since(cursor):
                cur = conn.execute(_sql("insert_report"),
                                   tuple(row.get(c) for c in REPORT_COLUMNS) + (1,))
                inserted += cur.rowcount
        return inserted
    finally:
        conn.close()


def list_reports(db_path: Union[str, Path]) -> list[dict]:
    """Report metadata (no text), newest first."""
    conn = get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(_sql("list_reports")).fetchall()]
    finally:
        conn.close()


def get_report(db_path: Union[str, Path], report_id: str) -> Optional[dict]:
    """One full report row (with text and synced) by id, or None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(_sql("get_report"), (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

- [ ] `local_sync.py` — at the end of `run_local_sync`, after the tracks `finally`, add `reports_pushed = push_unsynced(db_path, worker)` and `reports_pulled = pull_reports(db_path, worker)` (import at top), and add both to the result dict. Update the module's "pull-only" header comment (reports are written locally first — spec invariant change).

- [ ] `report/__main__.py`:
  - `--period-type`: `default="weekly", choices=["weekly", "monthly", "quarterly"]`
  - add `p.add_argument("--no-save", action="store_true", help="skip local save + push (throwaway run)")`
  - after `print(result.text)`:

```python
    if not args.no_save:
        import os
        import uuid
        from datetime import datetime, timezone

        from spotify_core.db.report_store import push_unsynced, save_report_local
        from spotify_core.db.worker_client import WorkerClient

        db_path = str(args.db or settings.history_db_path)
        save_report_local(db_path, {
            "id": str(uuid.uuid4()),
            "style": args.style,
            "period_type": args.period_type,
            "start_date": args.start,
            "end_date": args.end,
            "provider": args.provider,
            "model": args.model or settings.gemini_model,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "revision_count": result.revision_count,
            "report_text": result.text,
        })
        worker_url = os.environ.get("WORKER_URL")
        worker_token = os.environ.get("WORKER_AUTH_TOKEN")
        if worker_url and worker_token:
            try:
                with WorkerClient(worker_url, worker_token) as worker:
                    push_unsynced(db_path, worker)
            except Exception as exc:  # fail-soft: row stays synced=0, retried next sync
                print(f"warning: report push failed ({exc})", file=sys.stderr)
```

  - `graph.py`: default `period_type="weekly"` (was `"custom"`), update docstring. Grep `report/` for `"custom"` first — prompts take the string verbatim; if any node *branches* on it, stop and flag.
  - The existing pre-existing CLI test's fake result class needs `revision_count = 0` added (it now gets read on save) — or it passes `--no-save`; add the attribute.

- [ ] One test file, `tests/core/test_report_store.py` (the money path — outbox round-trip + idempotent push/pull):

```python
import httpx

from spotify_core.db.report_store import (
    get_report, list_reports, pull_reports, push_unsynced, save_report_local,
)
from spotify_core.db.worker_client import WorkerClient


def _row(i="00000000-0000-4000-8000-000000000001", gen="2026-07-20T10:00:00Z"):
    return {
        "id": i, "style": "roast", "period_type": "weekly",
        "start_date": "2026-07-06", "end_date": "2026-07-12",
        "provider": "google", "model": "gemini-3.5-flash",
        "generated_at": gen, "revision_count": 1, "report_text": "# hi",
    }


def _worker(handler):
    return WorkerClient("https://w.example", "tok",
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_save_push_pull_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    save_report_local(db, _row())
    save_report_local(db, _row())  # idempotent
    assert len(list_reports(db)) == 1
    assert get_report(db, _row()["id"])["synced"] == 0

    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(request)
            return httpx.Response(200, json={"inserted": 1})
        assert request.url.params["since"] == "2026-07-20T10:00:00Z"
        remote = _row(i="00000000-0000-4000-8000-000000000002",
                      gen="2026-07-20T11:00:00Z")
        return httpx.Response(200, json={"reports": [remote]})

    worker = _worker(handler)
    assert push_unsynced(db, worker) == 1
    assert get_report(db, _row()["id"])["synced"] == 1
    assert push_unsynced(db, worker) == 0          # outbox drained
    assert pull_reports(db, worker) == 1           # cursor pull, stored synced=1
    assert len(list_reports(db)) == 2
```

- [ ] Verify: `uv run pytest` → all green (fix the existing local_sync/CLI tests if the new result keys or `revision_count` read break them). Commit: `feat: report persistence — store, worker client, sync, CLI save/--no-save`

---

### Task 3: Worker endpoints + deploy

**Files:** create `worker/src/reports.ts`; modify `worker/src/index.ts`.

- [ ] `worker/src/reports.ts`:

```ts
import type { Env } from "./tracks";

export interface ReportRow {
  id: string;
  style: string;
  period_type: string;
  start_date: string;
  end_date: string;
  provider: string;
  model: string;
  generated_at: string;
  revision_count: number;
  report_text: string;
}

const COLUMNS = [
  "id", "style", "period_type", "start_date", "end_date",
  "provider", "model", "generated_at", "revision_count", "report_text", "synced",
] as const;

// synced is local-only bookkeeping; anything in D1 is synced by definition.
const INSERT_SQL = `INSERT OR IGNORE INTO reports (${COLUMNS.join(
  ", "
)}) VALUES (${COLUMNS.map(() => "?").join(", ")})`;

function badRequest(message: string): Response {
  return new Response(message, { status: 400 });
}

function isReportRow(value: unknown): value is ReportRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === "string" &&
    typeof row.generated_at === "string" &&
    typeof row.report_text === "string"
  );
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}T/;

/** POST /api/reports body = one report row -> { inserted: 0|1 } */
export async function handlePostReport(request: Request, env: Env): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("Malformed JSON body");
  }
  if (!isReportRow(body)) return badRequest("Report requires id, generated_at, report_text");

  const result = await env.DB.prepare(INSERT_SQL)
    .bind(
      body.id, body.style ?? "", body.period_type ?? "", body.start_date ?? "",
      body.end_date ?? "", body.provider ?? "", body.model ?? "",
      body.generated_at, body.revision_count ?? 0, body.report_text, 1
    )
    .run();
  return Response.json({ inserted: result.meta.changes ?? 0 });
}

/** GET /api/reports?since=<iso> -> { reports: [...] } */
export async function handleGetReports(request: Request, env: Env): Promise<Response> {
  const since = new URL(request.url).searchParams.get("since");
  if (since === null || !ISO_RE.test(since)) return badRequest("Provide 'since' (ISO-8601)");
  const { results } = await env.DB.prepare(
    "SELECT * FROM reports WHERE generated_at > ? ORDER BY generated_at ASC"
  ).bind(since).all();
  return Response.json({ reports: results });
}
```

- [ ] `index.ts`: `import { handleGetReports, handlePostReport } from "./reports";` + two routes after the `/api/tracks` POST:

```ts
    if (pathname === "/api/reports" && method === "GET") {
      return handleGetReports(request, env);
    }
    if (pathname === "/api/reports" && method === "POST") {
      return handlePostReport(request, env);
    }
```

- [ ] Verify: `cd worker && npm run typecheck`. Then (production — confirm with user first):

```bash
npx wrangler d1 migrations apply spotify-analytics --remote
npx wrangler deploy
```
Smoke: `curl -H "Authorization: Bearer $WORKER_AUTH_TOKEN" "$WORKER_URL/api/reports?since=1970-01-01T00:00:00Z"` → `{"reports":[]}`.
- [ ] Commit: `feat(worker): report CRUD endpoints`

---

### Task 4: Tauri — rename, Rust commands, sync, queries, ReportPage

**Files:** modify `apps/tauri/src/lib/period.ts`, `lib/sync.ts`, `lib/queries.ts`, `App.vue`, `ReportPage.vue`, `src-tauri/src/lib.rs`, `src-tauri/Cargo.toml`.

- [ ] **Rename `seasonal` → `quarterly`** in `period.ts`: type `ReportPeriod`, the `periodType: "custom"` return → `"quarterly"`, comment, and the self-check block (both `"seasonal"` args and both `periodType` expectations). In `ReportPage.vue`: `<option value="quarterly">Last quarter</option>`. Check: `npx tsx src/lib/period.ts` → self-check OK.

- [ ] **Rust** (`src-tauri`): `cargo add rfd@0.15`. In `lib.rs`:
  - `generate_report` args: append `"--no-save",` after `"--model", &model,` (Tauri persists only via the Save button).
  - Add two commands + register `tauri::generate_handler![generate_report, export_report_md, confirm_dialog]`:

```rust
// ponytail: rfd off-main-thread is fine on Windows; macOS needs main-thread —
// swap to tauri-plugin-dialog when cross-platform ships.
#[tauri::command]
async fn export_report_md(content: String, suggested_name: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let Some(path) = rfd::FileDialog::new()
            .set_file_name(&suggested_name)
            .add_filter("Markdown", &["md"])
            .save_file()
        else {
            return Ok(false);
        };
        std::fs::write(&path, content).map_err(|e| e.to_string())?;
        Ok(true)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn confirm_dialog(title: String, message: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        Ok(rfd::MessageDialog::new()
            .set_title(&title)
            .set_description(&message)
            .set_buttons(rfd::MessageButtons::YesNo)
            .show()
            == rfd::MessageDialogResult::Yes)
    })
    .await
    .map_err(|e| e.to_string())?
}
```

- [ ] **`sync.ts`** — add `syncReports()` (push outbox, then cursor pull; fail-soft). New imports: `insert_report.sql`, `unsynced_reports.sql`, `mark_report_synced.sql`, `max_report_generated_at.sql` (all `@sql/...?raw`). Update the header comment (mirror now holds locally-written report rows). Export `ReportRow`:

```ts
export interface ReportRow {
  id: string; style: string; period_type: string;
  start_date: string; end_date: string; provider: string; model: string;
  generated_at: string; revision_count: number; report_text: string;
}

/** Push local synced=0 report rows, then pull D1 rows behind the generated_at cursor. */
export async function syncReports(): Promise<{ pushed: number; pulled: number } | { offline: true }> {
  if (!__WORKER_URL__) return { offline: true };
  try {
    const db = await getDb();
    const auth = { Authorization: `Bearer ${__WORKER_AUTH_TOKEN__}` };

    const unsynced = await db.select<ReportRow[]>(unsyncedReportsSql);
    let pushed = 0;
    for (const r of unsynced) {
      const res = await fetch(`${__WORKER_URL__}/api/reports`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify(r),
      });
      if (!res.ok) break; // fail-soft: rows stay synced=0, retried next startup
      await db.execute(markReportSyncedSql, [r.id]);
      pushed++;
    }

    const cursorRows = await db.select<{ c: string | null }[]>(maxReportGeneratedAtSql);
    const cursor = cursorRows[0]?.c ?? EPOCH;
    const res = await fetch(
      `${__WORKER_URL__}/api/reports?since=${encodeURIComponent(cursor)}`,
      { headers: auth }
    );
    if (!res.ok) return { pushed, pulled: 0 };
    const body = (await res.json()) as { reports: ReportRow[] };
    let pulled = 0;
    for (const r of body.reports ?? []) {
      const result = await db.execute(insertReportSql, [
        r.id, r.style, r.period_type, r.start_date, r.end_date,
        r.provider, r.model, r.generated_at, r.revision_count, r.report_text, 1,
      ]);
      pulled += result.rowsAffected;
    }
    return { pushed, pulled };
  } catch (e) {
    console.error("syncReports failed:", e);
    return { offline: true };
  }
}
```

- [ ] **`queries.ts`** — append (imports: the four `@sql` files below, `getDb`, `type ReportRow` from `./sync`):

```ts
export type ReportMeta = Omit<ReportRow, "report_text">;

export async function listReports(): Promise<ReportMeta[]> {
  return (await getDb()).select<ReportMeta[]>(listReportsSql);
}

export async function getReportText(id: string): Promise<string | null> {
  const rows = await (await getDb()).select<{ report_text: string }[]>(getReportSql, [id]);
  return rows[0]?.report_text ?? null;
}

export async function reportExistsForPeriod(start: string, end: string): Promise<boolean> {
  const rows = await (await getDb()).select<{ c: number }[]>(countReportsForPeriodSql, [start, end]);
  return (rows[0]?.c ?? 0) > 0;
}

export async function saveReportLocal(row: ReportRow): Promise<void> {
  await (await getDb()).execute(insertReportSql, [
    row.id, row.style, row.period_type, row.start_date, row.end_date,
    row.provider, row.model, row.generated_at, row.revision_count,
    row.report_text, 0,
  ]);
}
```

- [ ] **`App.vue`** — after the existing `await syncOnStartup()` call: `syncReports().catch(console.error);` (import from `./lib/sync`).

- [ ] **`ReportPage.vue`** — new state + handlers (imports: `onMounted`, the four query fns + `ReportMeta`, `syncReports` + `ReportRow`):

```ts
const saved = ref(false);
const pastReports = ref<ReportMeta[]>([]);
// params of the currently displayed report (outlive the selects)
const lastRun = ref<{ start: string; end: string; periodType: string } | null>(null);

onMounted(async () => {
  if (isTauri) pastReports.value = await listReports();
});
```

`generate()` — dup-check before invoke, remember the run, reset `saved`:

```ts
async function generate() {
  const { start, end, periodType } = periodRange(period.value);
  if (await reportExistsForPeriod(start, end)) {
    const ok = await invoke<boolean>("confirm_dialog", {
      title: "Report exists",
      message: `A report for ${start} → ${end} is already saved. Generate another? (Saving keeps both.)`,
    });
    if (!ok) return;
  }
  running.value = true;
  error.value = "";
  try {
    report.value = await invoke<string>("generate_report", {
      style: style.value, start, end, periodType,
      provider: provider.value, model: model.value,
    });
    caption.value = `${style.value} · ${model.value} · ${start} → ${end}`;
    lastRun.value = { start, end, periodType };
    saved.value = false;
  } catch (e) {
    error.value = String(e);
  } finally {
    running.value = false;
  }
}

async function saveToDb() {
  if (!lastRun.value || !report.value) return;
  await saveReportLocal({
    id: crypto.randomUUID(),
    style: style.value,
    period_type: lastRun.value.periodType,
    start_date: lastRun.value.start,
    end_date: lastRun.value.end,
    provider: provider.value,
    model: model.value,
    generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    revision_count: 0, // ponytail: CLI prints markdown only; thread real count through when it matters
    report_text: report.value,
  }); // synced=0 — survives offline
  saved.value = true;
  pastReports.value = await listReports();
  syncReports().catch(console.error); // fail-soft push; retried on next startup
}

async function exportMd() {
  if (!lastRun.value || !report.value) return;
  await invoke("export_report_md", {
    content: report.value,
    suggestedName: `report-${style.value}-${lastRun.value.start}.md`,
  });
}

async function openReport(meta: ReportMeta) {
  const text = await getReportText(meta.id);
  if (text === null) return;
  report.value = text;
  caption.value = `${meta.style} · ${meta.model} · ${meta.start_date} → ${meta.end_date}`;
  lastRun.value = { start: meta.start_date, end: meta.end_date, periodType: meta.period_type };
  saved.value = true; // already persisted
}
```

Template — buttons after the `report-html` div (inside `v-if="report"`), list after that block (inside `.card`; reuse existing classes, minimal scoped styling for the list):

```html
      <div class="action">
        <button class="range-btn" :disabled="saved" @click="saveToDb">
          {{ saved ? "Saved" : "Save to DB" }}
        </button>
        <button class="range-btn" @click="exportMd">Export .md</button>
      </div>
```
```html
    <template v-if="pastReports.length">
      <h3>Past reports</h3>
      <ul class="past-reports">
        <li v-for="r in pastReports" :key="r.id">
          <a href="#" @click.prevent="openReport(r)">
            {{ r.start_date }} → {{ r.end_date }} · {{ r.style }} · {{ r.model }}
          </a>
        </li>
      </ul>
    </template>
```

- [ ] Verify: `cargo check` clean; `npm run build` clean; then one manual pass in `npm run tauri dev`:
  generate (nothing persisted) → Save to DB (button flips, list updates, row lands in D1) → same-period generate triggers confirm → Export .md writes the file → restart survives → delete `history.db` resyncs from D1 minus unsynced.
- [ ] Commit: `feat(tauri): quarterly rename, report save/export/list UI, report sync, rfd dialogs`

---

### Task 5: MCP read tools

**Files:** modify `apps/mcp/spotify_mcp/db_crud.py` (append beside `get_listening_summary`, same decorator/error pattern).

- [ ] Add two tools (no new tests — logic is a passthrough over the Task-2-tested store):

```python
    @mcp.tool(
        name="list_reports",
        annotations={
            "title": "List Saved AI Reports",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    def list_reports() -> list[dict]:
        """List saved AI report metadata (no text), newest first.

        Returns: [{"id", "style", "period_type", "start_date", "end_date",
                   "provider", "model", "generated_at", "revision_count"}, ...]
        """
        try:
            from spotify_core.db.report_store import list_reports as _list
            return _list(DB_PATH)
        except Exception as exc:
            logger.error("[Tool] list_reports failed: {}", exc)
            return [{"error": str(exc)}]

    @mcp.tool(
        name="get_report",
        annotations={
            "title": "Get a Saved AI Report",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    def get_report(report_id: str) -> dict:
        """Return one saved AI report (including its markdown text) by id.

        Args:
            report_id: The report uuid from list_reports.
        """
        try:
            from spotify_core.db.report_store import get_report as _get
            row = _get(DB_PATH, report_id)
            return row if row else {"error": f"no report with id {report_id}"}
        except Exception as exc:
            logger.error("[Tool] get_report failed: {}", exc)
            return {"error": str(exc)}
```

- [ ] Verify: `uv run pytest` (existing MCP lifespan tests still green). Commit: `feat(mcp): list_reports and get_report read tools`

---

### Notes

- **LangSmith:** env keys already in `.env.example`; tracing verified working via env vars — no code.
- **Tauri-saved `revision_count` is 0** (CLI stdout is markdown-only); CLI/MCP saves carry the real count.
- Deferred per spec: search/filter, delete/retention, history page, streaming.
