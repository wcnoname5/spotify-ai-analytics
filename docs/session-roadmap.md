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

### 2. One-time setup → Tauri GUI — **DONE 2026-07-22** (absorbs the old packaging-hardening items)
Spawned-Python front-end over the existing wizard steps, not a rewrite. Spec (approved): `docs/superpowers/specs/2026-07-20-tauri-setup-gui-design.md` — scope was Phase 0–2 with Phase 3 (cloud) deferred; Phase 3 was pulled forward and is also done. Everything below is verified on a running app, not just typechecked.
- [x] Phase 0: build-time Vite `define` → runtime config. Both reads and writes go through Python (`config get` / `config set`) — the effective `HISTORY_DB_PATH` needs `config.Settings` precedence + relative-path resolution, so a Rust-side `.env` parse would have been wrong. Token no longer in the bundle (verified absent)
- [x] **Design rule for step 3:** every promptless entry is a `spotify-mcp` subcommand, so packaging bundles ONE exe. Net new surface was only `path --json`, `doctor --json`, `config get/set/keygen` — `reauth` and `import-history --from` were already promptless
- [x] Phase 1+2 Setup page: shows only what's missing (`Show all settings` to edit anything), doctor-driven status, forms, OAuth + history import. Fernet key auto-generates when absent — it needs no user decision. Langfuse/LangSmith are one-of-two, not both
    - *Note:* LangSmith keys were already in `.env.example`; picking it also writes `LANGSMITH_TRACING=true`, without which the key traces nothing
- [x] Twin `.env`: already solved by `paths.py` (explicit override → `DEV=true` → platformdirs). The stale duplicate `TOKEN_ENCRYPT_KEY` was deleted 2026-07-20
- [x] **Verified on a running app (2026-07-22, Env A scratch dirs + second Spotify account):** `openUrl` works under `opener:default`, and the OAuth / import buttons work end-to-end
- [x] UX pass (`docs/2026-07-22-setup-ux-and-testing.md`): cloud step promoted ahead of llm/tracing, LLM now Skippable, encryption-key backup notice on step 1, cloud reframed "recommended"
- [x] The app is **gated on setup**: the main window starts hidden and an unconfigured launch shows only Preferences. Closing Preferences while the main window is still hidden exits, or the process would survive with no window and no way back
- [x] First-run check reuses the memoized `config get` instead of a second `doctor --json` spawn (`configured.client_id` was added for it)
- [x] `Done` closes Preferences and reveals the dashboard; one component serves both the wizard (fresh env) and Preferences (`showAll` defaults on once `client_id` exists) — not two pages
- [x] `DEV · <env_file>` badge in both windows: the twin-`.env` confusion was a *display* gap, `paths.py`'s resolution order was never ambiguous
- Fresh-environment testing without touching your `.env`:
  `SPOTIFY_MCP_CONFIG_DIR=/tmp/fresh SPOTIFY_MCP_DATA_DIR=/tmp/fresh/data npm run tauri dev`
- **Cache lesson (cost real debugging time):** `getConfig()` memoizes per window, and each webview is its own JS context. Anything that writes the `.env` from outside `setConfig` — `cloud deploy`, `keygen` — must call `invalidateConfig()`, or the UI keeps serving the config captured at app start. That is what stranded the wizard on step 4/6 after a successful deploy.

**Phase 3 (cloud deploy in the GUI) — done 2026-07-22, ahead of the trigger conditions.** Brought forward because packaging removes the checkout a user would need to run a `.sh` from, and because `setup_cloud.sh`'s front half (prompt for client_id, generate the Fernet key, bash `.env` parsing) was dead weight once the wizard guaranteed all of it.
- [x] `spotify-mcp cloud deploy` / `cloud seed` replace `scripts/setup_cloud.sh` (deleted). The GUI calls **the subcommand**, never wrangler — that indirection is the whole design: swapping wrangler for the Cloudflare REST API at packaging time touches one Python file.
- [x] Deploy button + streamed log in the Cloud card; `--api-token` avoids the interactive `wrangler login` that would hang a spawned child
- [x] Bearer token is reused across deploys (was regenerated every run, silently 401ing other machines); `--rotate` is the opt-in, surfaced as the Rotate button
- [x] `--name` + a throwaway wrangler config per run — `worker/wrangler.toml` is no longer written by tooling, which is what makes an Env B test stack safe
- [x] **Verified against real Cloudflare 2026-07-22** on a disposable stack (created and torn down; prod D1/Worker untouched): deploy with no OAuth, deploy with OAuth + 50 rows, re-deploy idempotency, `--rotate`, bad API token, missing client_id. The rotate case made the seed retry loop fire twice and recover — the path that used to abort the whole deploy
- [ ] **Still requires `node`/`npx`.** The REST swap (see §3) is what removes it for packaged users
- Bugs that only a real run surfaced, all Windows/CLI-specific and invisible to the GUI: `npx` is `npx.cmd` (needs `shutil.which`, not `shell=True`); wrangler's emoji output crashed a `cp950` console outside Tauri's `PYTHONUTF8`; `d1 migrations apply` is interactive, so stdin is now `DEVNULL` + `CI=1`

### 3. PyInstaller packaging (downloadable app)
Bundle the single `spotify-mcp` CLI (report + setup subcommands) as the Tauri sidecar; `REPORT_CMD` is the one-line swap.
- [ ] PyInstaller spike: size / startup / AV false positives on Windows first; decision gate — if unworkable, documented "requires local Python/uv" mode
- [ ] Packaged-app db path: keep `HISTORY_DB_PATH` override, default to appDataDir outside the repo
- [ ] Wire the sidecar into the spawn points; macOS/Linux story noted, not blocking
- Known breakages to fix *at* packaging (found while building §2, none fixable earlier):
  - `cloud.worker_dir()` resolves `Path(__file__).parents[3]` — no such path inside a bundle; needs `sys._MEIPASS` and `worker/` shipped as data
  - `paths.is_dev()` reads `Path.cwd()/.env`, and a frozen app's cwd is wherever it was launched. Add `if getattr(sys, "frozen", False): return False` — that one line ends the twin-`.env` class for shipped users permanently
  - every `npx`/Python spawn flashes a console window in a frozen GUI app; needs `CREATE_NO_WINDOW`
  - **the REST swap**: replace wrangler inside `cloud.py` with Cloudflare REST (`POST /d1/database` → `/query` for migrations → `PUT /workers/scripts/{name}` with the bundled JS → `/schedules` for the cron). Requires the Worker pre-bundled with esbuild. The GUI and CLI surface do not change — that was the point of routing the GUI through a subcommand

### 4. Docs + small fixes → pre-release v0.1
- [ ] README / DEPLOY / setup docs pass for a first-time user
- [ ] Small fixes: Tauri external links via plugin-opener; timezone display consistency (charts local vs tables UTC); sync-failure reason surfaced in UI
- [ ] MCP setting: add `menu` option in tauri after settup. pops out a window with copied json & path so that user 
- [ ] Tag v0.1 pre-release
- Post-release backlog: artist/source dimension filters (pure SQL), report streaming/cancellation, Langfuse in-app toggle
- comment: Add a langsmith version since it is more accessable to normal user than langfuse. (optional)

### Ride list (known, deliberately unfixed)
sqlx pulls mysql/pg deps via tauri-plugin-sql (upstream); Recently Played is now global last-50 (not range-scoped); sync failures show no reason detail in UI (console only); `plays_by_hour.sql` is TS-only and `activity_pattern.sql` is Python/report-only (both by design).
