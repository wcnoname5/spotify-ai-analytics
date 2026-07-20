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
Spawned-Python front-end over the existing wizard steps, not a rewrite. Spec (approved): `docs/superpowers/specs/2026-07-20-tauri-setup-gui-design.md` — implementation scope Phase 0–2; Phase 3 (cloud) specified but deferred.
- [x] Phase 0: build-time Vite `define` → runtime config. Both reads and writes go through Python (`config get` / `config set`) — the effective `HISTORY_DB_PATH` needs `config.Settings` precedence + relative-path resolution, so a Rust-side `.env` parse would have been wrong. Token no longer in the bundle (verified absent)
- [x] **Design rule for step 3:** every promptless entry is a `spotify-mcp` subcommand, so packaging bundles ONE exe. Net new surface was only `path --json`, `doctor --json`, `config get/set/keygen` — `reauth` and `import-history --from` were already promptless
- [x] Phase 1+2 Setup page: shows only what's missing (`Show all settings` to edit anything), doctor-driven status, forms, OAuth + history import. Fernet key auto-generates when absent — it needs no user decision. Langfuse/LangSmith are one-of-two, not both
    - *Note:* LangSmith keys were already in `.env.example`; picking it also writes `LANGSMITH_TRACING=true`, without which the key traces nothing
- [x] Twin `.env`: already solved by `paths.py` (explicit override → `DEV=true` → platformdirs). The stale duplicate `TOKEN_ENCRYPT_KEY` was deleted 2026-07-20
- [ ] **Not yet verified on a running app:** `openUrl` capability (`opener:default` may need `opener:allow-open-url`), and the OAuth / import buttons end-to-end
- Fresh-environment testing without touching your `.env`:
  `SPOTIFY_MCP_CONFIG_DIR=/tmp/fresh SPOTIFY_MCP_DATA_DIR=/tmp/fresh/data npm run tauri dev`

**Phase 3 (wrangler orchestration in the GUI) — when to do it.** Currently the GUI does the cheap half: prereq check, open docs, paste `WORKER_URL` + token; `scripts/setup_cloud.sh` does the deploy. Do the full version only when *both* hold:
1. **Packaging shipped** (section 3). Until then every user has a repo checkout and `uv`, so they can run `setup_cloud.sh` directly — a GUI wrapper saves them nothing.
2. **Pasting the token is the observed blocker** for a real non-developer user. If people get through cloud setup fine, this is the most work for the least-used screen (once per user, per lifetime).

If neither holds by v0.1, ship the paste screen and revisit post-release. Cost note: it cannot be tested without a real Cloudflare account and an actual deploy, so it also carries the worst verification story of anything on this roadmap.

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
