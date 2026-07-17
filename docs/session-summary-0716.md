# Session Summary — 2026-07-16

Branch: `frontend-tauri` (9 commits, b11d72d..d667d62, **not merged**).
Spec/plan: `docs/superpowers/specs/2026-07-16-shared-sql-local-cache-design.md`, `docs/superpowers/plans/2026-07-16-shared-sql-local-cache.md`.

## What's done

- **Shared SQL module**: analytics SQL extracted into 17 `.sql` files in `packages/core/spotify_core/db/sql/` — the single source of truth for query logic, used by BOTH Python and TypeScript. Convention: `?1`=start, `?2`=end (pre-widened), `?3`=tz modifier, NULL-guards for optional filters.
- **Python refactored**: `queries.py` / `schema.py` / `local_sync.py` load the `.sql` files (importlib.resources); public API unchanged except `show_track_id` removed (track_id always returned). Pytest 219 green.
- **Tauri dashboard reads the local cache**: `db.ts` / `queries.ts` / `sync.ts` over tauri-plugin-sql against the shared `data/history.db`; `syncOnStartup()` pulls new rows from the Worker on launch. The Vite proxy / raw-rows / frontend-JS-aggregation path is deleted. Browser `npm run dev` = sample data only; real data = `npm run tauri dev`. **Worker frozen — no aggregation endpoints, ever; new dashboard queries are local `.sql` changes.**
- **Reviewed and hardened**: per-task + whole-branch review; fixed the sqlx-pool transaction hazard (no BEGIN/COMMIT through tauri-plugin-sql), `load()` error fallback to sample data, offline/unconfigured notice split, README + `.env.example`.
- **Visually verified, 3 runtime bugs fixed** (`d667d62`): `sql:allow-execute` capability (not in `sql:default`); strip `--` comments before splitting `schema.sql` (comments contain `;`); sync fetch via `@tauri-apps/plugin-http` because the webview's fetch enforces CORS against the CORS-less Worker (Rust-side fetch, capability scoped to `https://*.workers.dev`).

## To-be-done roadmap

### 1. Report CLI entry script (next up)
Decouple the existing LangGraph report engine from the wizard/MCP flow into a spawn-per-call script.
- [ ] `scripts/report.py`: args `--style`, `--period` (+ dates), reads local `history.db`, prints the report to stdout
- [ ] Reuse `spotify_core/report/` engine as-is; no new engine code
- [ ] Verify: `uv run python scripts/report.py --style casual --period 30d` produces a report

### 2. PyInstaller sidecar spike (biggest unknown — do before any report UI work)
Prove the report engine can ship inside the Tauri app.
- [ ] PyInstaller-bundle `scripts/report.py` with the LangGraph/LangChain dependency tree
- [ ] Measure binary size + startup time; try on Windows first, note macOS/Linux story
- [ ] Decision gate: if unworkable (size/AV false positives), fall back to "requires local Python/uv" documented mode
- [ ] Only after the spike: Tauri `Report` button → sidecar spawn → stream output into the UI

### 3. Custom date range + dimension filters (now pure SQL, no Worker work)
- [ ] Date range picker in App.vue (native `<input type="date">` ×2), feeding the existing `{start, end}` range params
- [ ] Artist/source filter: new `.sql` variants (or add `?N` filter params to existing files) + thin wrappers both sides

### 4. Packaging hardening (before any distribution)
- [ ] `WORKER_AUTH_TOKEN` → OS keychain, Worker calls move fully to the Rust side (plugin-http path already established); remove the Vite `define` inline
- [ ] Packaged-app db path: keep `HISTORY_DB_PATH` override, default to appDataDir when not in the repo
- [ ] Tauri external links via plugin-opener; timezone display consistency check (charts local vs tables UTC)

### Ride list (known, deliberately unfixed)
sqlx pulls mysql/pg deps via tauri-plugin-sql (upstream); Recently Played is now global last-50 (not range-scoped); sync failures show no reason detail in UI (console only); `plays_by_hour.sql` has no Python caller (TS-only by design).
