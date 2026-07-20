# Roadmap draft

Date: 2026-07-18

## Done so far

- Shared SQL module + local-cache dashboard (merged, PR #14).
- Custom date range, granularity + chart toggles in the dashboard.
- AI report in the app (branch `report-cli-sidecar`): process entry `python -m spotify_core.report` (`--style --start --end --period-type --provider --model`, markdown on stdout); Rust spawn command (`REPORT_CMD` const = sidecar swap point, `PYTHONUTF8=1`); Report page with menu nav, weekly/monthly/quarterly presets, provider+model selects, markdown→HTML (marked+DOMPurify). 

## Roadmap to first pre-release

### 1. Report history: storage + retrieval — DONE (PR #15, branch `report-db`)
Save generated reports so user/LLM can query past records. Decision: **no R2, no .txt files** — text is KB-scale, lives in a table.
- [x] `reports` table in D1 via `schema.sql` (style, period_type, start_date, end_date, provider, model, generated_at, revision_count, report_text)
- [x] Worker: plain CRUD `POST /api/reports` + `GET /api/reports?since=` (same cursor shape as `/api/tracks`; thaws the Worker freeze for CRUD only — aggregation stays banned)
- [x] App saves after successful generation; local `history.db` mirrors via the existing pull-sync pattern (keeps the cache disposable)
- [x] Past-reports UI (list + view) and MCP read access from the local mirror
- Riding: Tauri-saved rows carry `revision_count=0`; MCP report tools untested against a real server; same-second cursor edge (single-machine assumption)
- Fallback if avoiding cloud work: separate local `reports.db` (NOT inside history.db — it must stay a rebuildable mirror), upgrade path = add the push/pull later

### 2. One-time setup → Tauri GUI (absorbs the old packaging-hardening items)
Spawned-Python front-end over the existing wizard steps, not a rewrite. Draft spec: `docs/superpowers/specs/2026-07-18-tauri-setup-gui-design.md`.
- [ ] Phase 0 prereq: build-time Vite `define` config → runtime Rust `get_config`/`set_config` (`.env` or OS keychain); removes the token-in-bundle debt
- [ ] **Design rule for step 3:** every promptless entry is a `spotify-mcp` subcommand (`doctor --json`, `oauth`, `import-history --from`, ...) so packaging later bundles ONE exe 
- [ ] Setup page: doctor-driven step list, client-ID + LLM/Langfuse/LangSmith forms, Fernet keygen; then OAuth + history import; cloud setup stays script-first (GUI = prereq check + paste WORKER_URL/token)
    - *Note:* LangSmith feature is newly added, test tracing is fine w/ langsmith and add its API key to .`env.example` (for developing) before go on
- [ ] solve the legacy twin  `.env` (repo rott vs. `platformdirs` resolved path) problem. (keep one is okay)

### 3. PyInstaller packaging (downloadable app)
Bundle the single `spotify-mcp` CLI (report + setup subcommands) as the Tauri sidecar; `REPORT_CMD` is the one-line swap.
- [ ] PyInstaller spike: size / startup / AV false positives on Windows first; decision gate — if unworkable, documented "requires local Python/uv" mode
- [ ] Packaged-app db path: keep `HISTORY_DB_PATH` override, default to appDataDir outside the repo
- [ ] Wire the sidecar into the spawn points; macOS/Linux story noted, not blocking

### 4. Docs + small fixes → pre-release v0.1
- [ ] README / DEPLOY / setup docs pass for a first-time user
- [ ] Small fixes: Tauri external links via plugin-opener; timezone display consistency (charts local vs tables UTC); sync-failure reason surfaced in UI
- [ ] MCP setting: add `menu` option in tauri after settup. pops out a window with copied json & path so that user 
- [ ] Tag v0.1 pre-release
- Post-release backlog: artist/source dimension filters (pure SQL), report streaming/cancellation, Langfuse in-app toggle
- comment: Add a langsmith version since it is more accessable to normal user than langfuse. (optional)

### Ride list (known, deliberately unfixed)
sqlx pulls mysql/pg deps via tauri-plugin-sql (upstream); Recently Played is now global last-50 (not range-scoped); sync failures show no reason detail in UI (console only); `plays_by_hour.sql` is TS-only and `activity_pattern.sql` is Python/report-only (both by design).
