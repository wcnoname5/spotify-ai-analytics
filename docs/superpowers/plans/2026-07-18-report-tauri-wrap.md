# AI Report in Tauri (CLI entry + Rust spawn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report engine gets a `python -m spotify_core.report` entry point; the Tauri app grows a Report page that runs it via a Rust spawn command.

**Architecture:** Boundary is argv in → markdown on stdout. Rust spawns `uv run python -m spotify_core.report ...` (spawn_blocking, command vector in one const for a later sidecar swap). Frontend: menu toggle in App.vue (`v-show`, so report state survives page flips) + `ReportPage.vue` with style/period selects; period presets resolve to the last *completed* period client-side.

**Tech Stack:** Python argparse (stdlib), Rust std::process, Vue 3, existing `@tauri-apps/api` invoke. No new dependencies.

## Global Constraints

- Engine code (`spotify_core/report/` existing modules) untouched.
- stdout of the CLI carries **only** report markdown (loguru already goes to stderr).
- Styles: `listening_review`, `roast`. Periods: weekly = last completed Mon–Sun week; monthly = last completed calendar month; seasonal = last completed calendar quarter → `period_type` `"custom"`.
- API keys stay in root `.env` / inherited env; never in the frontend.

---

### Task 1: CLI entry `spotify_core/report/__main__.py`

**Files:**
- Create: `packages/core/spotify_core/report/__main__.py`
- Test: `tests/core/test_report_cli.py`

**Interfaces:**
- Produces: `python -m spotify_core.report --style S --start YYYY-MM-DD --end YYYY-MM-DD [--period-type weekly|monthly|custom] [--db PATH] [--provider P] [--model M]` → report markdown on stdout, exit 0; exit ≠0 with message on stderr on failure. Task 2 spawns exactly this.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_report_cli.py
import sys

from spotify_core.report.__main__ import main


def test_cli_prints_report_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(
        "spotify_core.report.models.build_chat_model", lambda provider, model: "fake-model"
    )

    def fake_generate(**kw):
        assert kw["style"] == "roast"
        assert kw["period_type"] == "weekly"
        assert kw["model"] == "fake-model"

        class R:
            text = "# Weekly Roast"

        return R()

    monkeypatch.setattr("spotify_core.report.graph.generate_report", fake_generate)
    monkeypatch.setattr(
        sys, "argv",
        ["report", "--style", "roast", "--start", "2026-07-06",
         "--end", "2026-07-12", "--period-type", "weekly"],
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == "# Weekly Roast"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_report_cli.py -v`
Expected: FAIL (`ModuleNotFoundError: spotify_core.report.__main__`)

- [ ] **Step 3: Implement**

```python
# packages/core/spotify_core/report/__main__.py
"""Process entry: uv run python -m spotify_core.report --style roast --start ... --end ...

Contract (spawned by the Tauri Rust backend): report markdown on stdout only,
diagnostics on stderr, non-zero exit on failure.
"""
import argparse
import sys


def main() -> int:
    p = argparse.ArgumentParser(prog="spotify_core.report")
    p.add_argument("--style", required=True, choices=["listening_review", "roast"])
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--period-type", default="custom", choices=["weekly", "monthly", "custom"])
    p.add_argument("--db", default=None, help="history.db path (default: settings)")
    p.add_argument("--provider", default="google")
    p.add_argument("--model", default=None, help="default: settings.gemini_model")
    args = p.parse_args()

    from spotify_core.config import settings
    from spotify_core.report.graph import generate_report
    from spotify_core.report.models import build_chat_model

    model = build_chat_model(args.provider, args.model or settings.gemini_model)
    result = generate_report(
        style=args.style,
        start_date=args.start,
        end_date=args.end,
        db_path=str(args.db or settings.history_db_path),
        model=model,
        period_type=args.period_type,
    )
    print(result.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/core/test_report_cli.py -v` → PASS, then `uv run pytest -q` → all green.

- [ ] **Step 5: Smoke the real thing (needs GEMINI_API_KEY in root .env)**

Run: `uv run python -m spotify_core.report --style roast --start 2026-07-06 --end 2026-07-12 --period-type weekly`
Expected: report markdown on stdout. Also confirm `... 2>NUL` (or `2>$null` in pwsh) still shows only the report.

- [ ] **Step 6: Commit**

```bash
git add packages/core/spotify_core/report/__main__.py tests/core/test_report_cli.py
git commit -m "feat: python -m spotify_core.report CLI entry (argv -> markdown on stdout)"
```

---

### Task 2: Rust `generate_report` command

**Files:**
- Modify: `apps/tauri/src-tauri/src/lib.rs`

**Interfaces:**
- Consumes: the Task 1 CLI.
- Produces: Tauri command `generate_report(style, start, end, period_type) -> Result<String, String>`; JS calls `invoke("generate_report", { style, start, end, periodType })` (Tauri maps camelCase → snake_case).

- [ ] **Step 1: Implement** — replace the `greet` demo command:

```rust
// apps/tauri/src-tauri/src/lib.rs
use std::path::Path;
use std::process::Command;

// ponytail: dev-only runner; a packaged PyInstaller sidecar swaps this vector + cwd.
const REPORT_CMD: &[&str] = &["uv", "run", "python", "-m", "spotify_core.report"];

#[tauri::command]
async fn generate_report(
    style: String,
    start: String,
    end: String,
    period_type: String,
) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let out = Command::new(REPORT_CMD[0])
            .args(&REPORT_CMD[1..])
            .args([
                "--style", &style, "--start", &start, "--end", &end,
                "--period-type", &period_type,
            ])
            .current_dir(&repo_root)
            .output()
            .map_err(|e| format!("failed to spawn `{}`: {e}", REPORT_CMD[0]))?;
        if out.status.success() {
            Ok(String::from_utf8_lossy(&out.stdout).into_owned())
        } else {
            let err = String::from_utf8_lossy(&out.stderr);
            // Last few lines are the actual Python error; the rest is log noise.
            let tail: Vec<&str> = err.lines().rev().take(12).collect();
            Err(tail.into_iter().rev().collect::<Vec<_>>().join("\n"))
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_sql::Builder::default().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![generate_report])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd apps/tauri/src-tauri && cargo check`
Expected: clean (warnings ok).

- [ ] **Step 3: Commit**

```bash
git add apps/tauri/src-tauri/src/lib.rs
git commit -m "feat(tauri): generate_report command spawns the python report CLI"
```

---

### Task 3: Period resolution helper

**Files:**
- Create: `apps/tauri/src/lib/period.ts`

**Interfaces:**
- Produces: `periodRange(period: ReportPeriod, now?: Date): { start: string; end: string; periodType: string }` — local dates `YYYY-MM-DD`, last completed period. Task 4 calls it.

- [ ] **Step 1: Implement**

```typescript
// apps/tauri/src/lib/period.ts
export type ReportPeriod = "weekly" | "monthly" | "seasonal";

const fmt = (dt: Date) =>
  `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

/** Last fully completed period (local time). Week starts Monday; seasonal = calendar quarter. */
export function periodRange(
  period: ReportPeriod,
  now = new Date()
): { start: string; end: string; periodType: string } {
  const y = now.getFullYear();
  const m = now.getMonth();
  if (period === "weekly") {
    const monOffset = (now.getDay() + 6) % 7; // Mon=0 .. Sun=6
    const lastSun = new Date(y, m, now.getDate() - monOffset - 1);
    const lastMon = new Date(lastSun.getFullYear(), lastSun.getMonth(), lastSun.getDate() - 6);
    return { start: fmt(lastMon), end: fmt(lastSun), periodType: "weekly" };
  }
  if (period === "monthly") {
    return { start: fmt(new Date(y, m - 1, 1)), end: fmt(new Date(y, m, 0)), periodType: "monthly" };
  }
  const q = Math.floor(m / 3); // current quarter; JS Date normalizes negative months
  return {
    start: fmt(new Date(y, (q - 1) * 3, 1)),
    end: fmt(new Date(y, q * 3, 0)),
    periodType: "custom",
  };
}

// Self-check, runs only under node (`npx tsx src/lib/period.ts`) — never in the webview.
if (typeof window === "undefined") {
  const now = new Date(2026, 6, 18); // Sat 2026-07-18
  const eq = (a: object, b: object) => JSON.stringify(a) === JSON.stringify(b) || (() => { throw new Error(`${JSON.stringify(a)} != ${JSON.stringify(b)}`); })();
  eq(periodRange("weekly", now), { start: "2026-07-06", end: "2026-07-12", periodType: "weekly" });
  eq(periodRange("monthly", now), { start: "2026-06-01", end: "2026-06-30", periodType: "monthly" });
  eq(periodRange("seasonal", now), { start: "2026-04-01", end: "2026-06-30", periodType: "custom" });
  eq(periodRange("seasonal", new Date(2026, 1, 10)), { start: "2025-10-01", end: "2025-12-31", periodType: "custom" }); // Q4 prev year
  eq(periodRange("weekly", new Date(2026, 6, 13)), { start: "2026-07-06", end: "2026-07-12", periodType: "weekly" }); // Monday
  console.log("period.ts self-check OK");
}
```

- [ ] **Step 2: Run the self-check**

Run: `cd apps/tauri && npx tsx src/lib/period.ts`
Expected: `period.ts self-check OK`

- [ ] **Step 3: Commit**

```bash
git add apps/tauri/src/lib/period.ts
git commit -m "feat(tauri): periodRange helper — last completed week/month/quarter"
```

---

### Task 4: Report page + menu

**Files:**
- Create: `apps/tauri/src/ReportPage.vue`
- Modify: `apps/tauri/src/App.vue` (add nav + `v-show` pages; delete the "Generate Report (coming soon)" placeholder card at the bottom of the dashboard)

**Interfaces:**
- Consumes: `periodRange` (Task 3); Tauri command `generate_report` via `invoke` (Task 2); `isTauri` from `./lib/db`.

- [ ] **Step 1: Create `ReportPage.vue`**

```vue
<script setup lang="ts">
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./lib/db";
import { periodRange, type ReportPeriod } from "./lib/period";

const style = ref<"listening_review" | "roast">("listening_review");
const period = ref<ReportPeriod>("weekly");
const running = ref(false);
const report = ref("");
const caption = ref("");
const error = ref("");

async function generate() {
  const { start, end, periodType } = periodRange(period.value);
  running.value = true;
  error.value = "";
  try {
    report.value = await invoke<string>("generate_report", {
      style: style.value, start, end, periodType,
    });
    caption.value = `${style.value} · ${start} → ${end}`;
  } catch (e) {
    error.value = String(e);
  } finally {
    running.value = false;
  }
}
</script>

<template>
  <div class="card">
    <h3>AI Report</h3>
    <p v-if="!isTauri" class="banner">Reports need the desktop app — run <code>npm run tauri dev</code>.</p>
    <div class="filters">
      <select v-model="style">
        <option value="listening_review">Listening review</option>
        <option value="roast">Roast</option>
      </select>
      <select v-model="period">
        <option value="weekly">Last week (Mon–Sun)</option>
        <option value="monthly">Last month</option>
        <option value="seasonal">Last quarter</option>
      </select>
      <button class="range-btn" :disabled="!isTauri || running" @click="generate">
        {{ running ? "Generating…" : "Generate" }}
      </button>
    </div>
    <p v-if="running">This takes a minute — multiple LLM calls.</p>
    <p v-if="error" class="banner">Report failed: <code>{{ error }}</code></p>
    <template v-if="report">
      <p class="period">{{ caption }}</p>
      <pre class="report-text">{{ report }}</pre>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Wire into `App.vue`**

In the script block, add imports and page state:

```typescript
import ReportPage from "./ReportPage.vue";
const page = ref<"dashboard" | "report">("dashboard");
```

In the template: insert a nav right under `<h1>`, wrap the existing dashboard content (from `<div class="filters">` through `</details>`'s parent `<div :class="{ loading }">`, including the banners) in `<div v-show="page === 'dashboard'">`, and add the report page. Delete the placeholder card (`<h3>Generate Report</h3>` … `coming soon` button):

```html
<h1>Spotify Listening Dashboard</h1>

<nav class="filters">
  <button class="range-btn" :class="{ current: page === 'dashboard' }" @click="page = 'dashboard'">Dashboard</button>
  <button class="range-btn" :class="{ current: page === 'report' }" @click="page = 'report'">Report</button>
</nav>

<div v-show="page === 'dashboard'">
  <!-- existing filters + banners + dashboard content, unchanged -->
</div>

<ReportPage v-show="page === 'report'" />
```

(`v-show`, not `v-if` — keeps both pages mounted so the report survives navigation.)

Add to `styles.css`:

```css
.report-text {
  white-space: pre-wrap;
  font-family: inherit;
  line-height: 1.6;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Verify in the app**

Run: `cd apps/tauri && npm run tauri dev` — switch to Report, Generate a weekly roast, confirm: spinner text while running, report + caption render, flipping Dashboard↔Report keeps the report, and an intentional failure (e.g. temporarily rename GEMINI_API_KEY in `.env`) shows the error banner.

- [ ] **Step 5: Commit**

```bash
git add apps/tauri/src/ReportPage.vue apps/tauri/src/App.vue apps/tauri/src/styles.css
git commit -m "feat(tauri): Report page — menu nav, period presets, spawned python report"
```
