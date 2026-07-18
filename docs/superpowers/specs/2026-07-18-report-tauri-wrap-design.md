# AI Report in the Tauri App (CLI entry + Rust spawn) — Design

**Date:** 2026-07-18
**Status:** Finished (commit `260ab4e`)
**Scope:** Give the report engine a process entry point and surface it in the Tauri dashboard by spawning Python from the Rust backend. Engine code (`spotify_core/report/`) is untouched and free to keep evolving — the boundary is argv in, markdown on stdout out.

## Decisions (settled with user)

1. **Process runner:** Rust spawns `uv run python -m spotify_core.report ...` (repo checkout, local Python/uv required — true for the only user). Command vector lives in one place so a future PyInstaller sidecar exe is a one-line swap. Sidecar spike = separate later branch.
2. **Entry point:** `packages/core/spotify_core/report/__main__.py` (not a `scripts/` file) — argparse shim over the existing `generate_report()`; doubles as the dev CLI.
3. **UX:** spinner → final report. No streaming, no cancellation (close app to abort).
4. **Own page:** the report lives on a separate page reached from a small top menu (plain view toggle in App.vue — no vue-router). Its period input is fully decoupled from the dashboard range.
5. **Periods — full completed periods only:** `weekly` = last completed Mon–Sun week; `monthly` = last completed calendar month (1st–end); `seasonal` = last completed calendar quarter (Q1–Q4). The frontend resolves the preset to concrete `{start, end}` dates; `period_type` passes `"weekly"` / `"monthly"` through to the engine, seasonal maps to `"custom"` (no engine change).
6. **Persistence:** the generated report has its own state slice; navigating between pages doesn't clear it. A caption shows the style + range it was generated from.

## Components

### 1. `spotify_core/report/__main__.py` (~40 lines)

- Args: `--style {listening_review,roast}` (required), `--start` / `--end` `YYYY-MM-DD` (required), `--period-type {weekly,monthly,custom}` (default `custom`), `--db` (default `settings.history_db_path`), `--provider` (default `google`), `--model` (default `settings.gemini_model`).
- Flow: `build_chat_model(provider, model)` → `generate_report(...)` → `print(result.text)`.
- Contract: **stdout carries only the report markdown**; loguru/diagnostics go to stderr; non-zero exit + stderr message on failure. Keys come from root `.env` via `spotify_core.config` (inherited env) — never through the frontend.
- Smoke: `uv run python -m spotify_core.report --style roast --start 2026-07-01 --end 2026-07-18`.

### 2. Rust command (`apps/tauri/src-tauri/src/lib.rs`)

- `#[tauri::command] async fn generate_report(style, start, end, period_type) -> Result<String, String>`: spawn the command vector with cwd = repo root, capture output; exit 0 → `Ok(stdout)`, else `Err(stderr tail)`.
- Repo root: resolved at compile time from the crate dir (`CARGO_MANIFEST_DIR/../../..`) — same dev-only assumption the injected db path already makes; packaged-app pathing is deferred with the sidecar.
- No Rust unit tests (thin spawn wrapper); no new crate deps if `std::process` + tauri's async runtime suffice.

### 3. Frontend (App.vue + a Report page component)

- Top menu toggles Dashboard / Report views (a ref + `v-if`); dashboard state and report state are independent.
- Report page: style `<select>` (`listening_review` / `roast`), period `<select>` (weekly / monthly / seasonal), Generate button → resolve the preset to concrete dates (week starts Monday; quarter = calendar Q1–Q4; always the last *completed* period) → `invoke("generate_report", {...})` → spinner while pending → render result with a style+range caption.
- Rendering: plain preformatted text first; add a tiny markdown renderer only if it reads badly.
- Error → non-blocking notice (reuse the existing notice pattern); browser mode (`npm run dev`) disables the button.

## Error handling

- Spawn failure / non-zero exit / missing API key: `Err` string from Rust → notice in UI; previous report (if any) stays rendered.
- No timeout in v1 — runs are minutes at worst and the UI stays responsive (`async` command).

## Testing

- Pytest untouched (no engine changes). Manual smoke of the CLI, one in-app run via `npm run tauri dev`.

## Explicitly deferred

- PyInstaller sidecar build + packaged-app path resolution (next branch; slots into the command vector).
- Streaming progress, cancellation, report history/saving, custom date-range reports, markdown renderer.
