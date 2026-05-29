# Dashboard Into App Package — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `uvx spotify-mcp dashboard` launch the Streamlit dashboard (viz + AI report) from the single published `spotify-analytics-mcp` package, retiring the `spotify-web` package entirely.

**Architecture:** Move the dashboard helpers (`charts`/`formatting`/`period_filter`/`runtime`) and the Streamlit pages (`main_page`/`views`/`ai_block`) into a new `spotify_mcp/dashboard/` subpackage; gate the Streamlit/Plotly/OpenAI deps behind a `[dashboard]` optional extra; add a `dashboard` CLI command that shells out to `streamlit run` against the packaged entry; gate the LLM/Langfuse wizard steps on the extra being installed; delete `apps/web/`.

**Tech Stack:** uv workspace, hatchling, typer, rich, streamlit, plotly, pytest, importlib.resources.

Spec: [docs/superpowers/specs/2026-05-29-dashboard-into-app-package-design.md](../specs/2026-05-29-dashboard-into-app-package-design.md)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `apps/mcp/spotify_mcp/dashboard/__init__.py` | Mark the dashboard subpackage |
| Move | `apps/web/spotify_web/charts.py` → `apps/mcp/spotify_mcp/dashboard/charts.py` | Plotly figure builders |
| Move | `apps/web/spotify_web/formatting.py` → `apps/mcp/spotify_mcp/dashboard/formatting.py` | Display formatting helpers |
| Move | `apps/web/spotify_web/period_filter.py` → `apps/mcp/spotify_mcp/dashboard/period_filter.py` | Period selection helpers |
| Move | `apps/web/spotify_web/config.py` → `apps/mcp/spotify_mcp/dashboard/runtime.py` | `get_sync_args` / `get_llm_config` / re-exported `get_client_id`/`get_fernet_key` |
| Move | `apps/web/ui/dashboard.py` → `apps/mcp/spotify_mcp/dashboard/views.py` | `render_dashboard()` |
| Move | `apps/web/ui/ai_block.py` → `apps/mcp/spotify_mcp/dashboard/ai_block.py` | `render_ai_block()` |
| Move | `apps/web/ui/main_page.py` → `apps/mcp/spotify_mcp/dashboard/main_page.py` | Streamlit entry (nav removed) |
| Delete | `apps/web/ui/chatbot_page.py` | Chat/agent page (out of scope) |
| Delete | `apps/web/` (whole dir) | Retire the `spotify-web` package |
| Modify | `apps/mcp/spotify_mcp/cli.py` | Add `dashboard` command |
| Modify | `apps/mcp/spotify_mcp/wizard/__init__.py` | Gate LLM/Langfuse steps on `[dashboard]` |
| Modify | `apps/mcp/pyproject.toml` | Add `[dashboard]` extra |
| Modify | `pyproject.toml` (root) | Drop `spotify-web` from workspace/sources/deps |
| Move | `tests/web/*` → `tests/dashboard/*` | Repointed helper tests |
| Modify | `tests/test_env_load_order.py` | Repoint `spotify_web.config` → `spotify_mcp.dashboard.runtime` |
| Create | `tests/mcp/test_cli_dashboard.py` | Cover the `dashboard` command |
| Create | `tests/mcp/test_wizard_gating.py` | Cover wizard gating |
| Modify | `CLAUDE.md`, `AGENTS.md` | Doc updates |
| Delete | `scripts/run_dashboard.bat`, `scripts/run_dashboard.sh` | Stale launchers |

---

# Phase 0 — Land `task-1-6` first

`task-1-6` consolidates env reads into `Settings` and adds the (currently ungated) LLM/Langfuse wizard steps. It edits the very files Phase 1 moves, so it must land first.

### Task 0: Rebase, review, and verify `task-1-6`

**Files:** none authored; integration only.

- [ ] **Step 1: Confirm a clean working tree on `cli-int`**

Run: `git status`
Expected: only intended changes; `cli-int` checked out.

- [ ] **Step 2: Rebase `task-1-6` onto `cli-int`**

```bash
git checkout task-1-6
git rebase cli-int
```
If conflicts arise, resolve them (the overlap is in `apps/web/spotify_web/config.py`, `tests/web/test_web_config.py`, `packages/core/spotify_core/{env,config,setup}.py`, `report/{models,observability}.py`). Keep the `settings`-based versions from `task-1-6`.

- [ ] **Step 3: Review the diff**

Run: `git diff cli-int...task-1-6 --stat` then read each changed file.
Confirm: `Settings` has `spotify_client_id`, `token_encrypt_key`, `fernet_key_bytes`, Langfuse fields; `env.py` helpers delegate to `settings`; wizard has `llm_keys.py` + `langfuse_keys.py`.

- [ ] **Step 4: Run the full suite on `task-1-6`**

Run: `uv run pytest -q`
Expected: all pass (parity with `cli-int`: 270 passed, 1 skipped, plus the new wizard/report tests).

- [ ] **Step 5: Fast-forward `cli-int` to the reviewed `task-1-6`**

```bash
git checkout cli-int
git merge --ff-only task-1-6
```
Expected: `cli-int` now contains Tasks 1–6.

- [ ] **Step 6: Re-run the suite on `cli-int`**

Run: `uv run pytest -q`
Expected: all pass. **Phase 0 complete.**

---

# Phase 1 — Dashboard refactor

> All Phase 1 work happens on `cli-int` (post-merge). Every task ends green.

### Task 1: Scaffold `dashboard/` and move the library modules

Moves the four importable helper modules + their tests. UI pages move in Task 2.

**Files:**
- Create: `apps/mcp/spotify_mcp/dashboard/__init__.py`
- Move: `apps/web/spotify_web/{charts,formatting,period_filter}.py` → `apps/mcp/spotify_mcp/dashboard/`
- Move: `apps/web/spotify_web/config.py` → `apps/mcp/spotify_mcp/dashboard/runtime.py`
- Move: `tests/web/{test_charts,test_formatting,test_period_filter}.py` → `tests/dashboard/`
- Move: `tests/web/test_web_config.py` → `tests/dashboard/test_runtime.py`
- Create: `tests/dashboard/__init__.py`
- Modify: `tests/test_env_load_order.py`

- [ ] **Step 1: Create the subpackage marker**

Create `apps/mcp/spotify_mcp/dashboard/__init__.py`:

```python
"""Streamlit dashboard (viz + AI report) shipped with the [dashboard] extra."""
```

- [ ] **Step 2: Move the library modules with git**

```bash
git mv apps/web/spotify_web/charts.py        apps/mcp/spotify_mcp/dashboard/charts.py
git mv apps/web/spotify_web/formatting.py    apps/mcp/spotify_mcp/dashboard/formatting.py
git mv apps/web/spotify_web/period_filter.py apps/mcp/spotify_mcp/dashboard/period_filter.py
git mv apps/web/spotify_web/config.py        apps/mcp/spotify_mcp/dashboard/runtime.py
```

- [ ] **Step 3: Fix any intra-module `spotify_web` imports**

Run: `git grep -n "spotify_web" -- apps/mcp/spotify_mcp/dashboard`
Expected: no output. If any line appears, replace `spotify_web.` with `spotify_mcp.dashboard.` in that file. (`runtime.py` imports only from `spotify_core`, so it needs no change.)

- [ ] **Step 4: Create the test package marker**

Create `tests/dashboard/__init__.py`:

```python
```
(empty file)

- [ ] **Step 5: Move the helper tests**

```bash
git mv tests/web/test_charts.py        tests/dashboard/test_charts.py
git mv tests/web/test_formatting.py    tests/dashboard/test_formatting.py
git mv tests/web/test_period_filter.py tests/dashboard/test_period_filter.py
git mv tests/web/test_web_config.py    tests/dashboard/test_runtime.py
git rm tests/web/__init__.py
```

- [ ] **Step 6: Repoint imports in the moved tests**

In `tests/dashboard/test_charts.py`:
`from spotify_web.charts import daily_activity_figure, trend_figure`
→ `from spotify_mcp.dashboard.charts import daily_activity_figure, trend_figure`

In `tests/dashboard/test_formatting.py`:
`from spotify_web.formatting import spotify_uri_to_url, format_duration_mins`
→ `from spotify_mcp.dashboard.formatting import spotify_uri_to_url, format_duration_mins`

In `tests/dashboard/test_period_filter.py`:
`from spotify_web.period_filter import resolve_period_dates`
→ `from spotify_mcp.dashboard.period_filter import resolve_period_dates`

In `tests/dashboard/test_runtime.py`, change the top import:
`from spotify_web import config as web_config`
→ `from spotify_mcp.dashboard import runtime as web_config`

- [ ] **Step 7: Repoint `tests/test_env_load_order.py`**

In the module-eviction list, replace `"spotify_web.config",` with `"spotify_mcp.dashboard.runtime",`. Then replace:

```python
    web_cfg = importlib.import_module("spotify_web.config")
    assert web_cfg.get_client_id() == "from_env_file"
```
with:
```python
    web_cfg = importlib.import_module("spotify_mcp.dashboard.runtime")
    assert web_cfg.get_client_id() == "from_env_file"
```

(`runtime.py` re-exports `get_client_id` via `from spotify_core.env import get_client_id, get_fernet_key`, so the attribute exists.)

- [ ] **Step 8: Run the moved + touched tests**

Run: `uv run pytest tests/dashboard tests/test_env_load_order.py -q`
Expected: all pass.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (UI pages in `apps/web/ui/` are not collected, so their now-stale `spotify_web` imports don't matter yet).

- [ ] **Step 10: Commit**

```bash
git add apps/mcp/spotify_mcp/dashboard tests/dashboard tests/test_env_load_order.py
git commit -m "refactor(dashboard): move web helpers into spotify_mcp.dashboard"
```

---

### Task 2: Move the Streamlit pages and drop the chat page

**Files:**
- Move: `apps/web/ui/dashboard.py` → `apps/mcp/spotify_mcp/dashboard/views.py`
- Move: `apps/web/ui/ai_block.py` → `apps/mcp/spotify_mcp/dashboard/ai_block.py`
- Move: `apps/web/ui/main_page.py` → `apps/mcp/spotify_mcp/dashboard/main_page.py`
- Delete: `apps/web/ui/chatbot_page.py`

- [ ] **Step 1: Move the page modules with git**

```bash
git mv apps/web/ui/dashboard.py apps/mcp/spotify_mcp/dashboard/views.py
git mv apps/web/ui/ai_block.py  apps/mcp/spotify_mcp/dashboard/ai_block.py
git mv apps/web/ui/main_page.py apps/mcp/spotify_mcp/dashboard/main_page.py
git rm apps/web/ui/chatbot_page.py
```

- [ ] **Step 2: Repoint imports in `views.py`**

Replace these import lines:
```python
from spotify_web.charts import daily_activity_figure, trend_figure
from spotify_web.config import get_sync_args
from spotify_web.formatting import format_duration_mins, spotify_uri_to_url

from ai_block import render_ai_block
from spotify_web.period_filter import DASHBOARD_PERIOD_OPTION, render_period_dates
```
with:
```python
from spotify_mcp.dashboard.charts import daily_activity_figure, trend_figure
from spotify_mcp.dashboard.runtime import get_sync_args
from spotify_mcp.dashboard.formatting import format_duration_mins, spotify_uri_to_url

from spotify_mcp.dashboard.ai_block import render_ai_block
from spotify_mcp.dashboard.period_filter import DASHBOARD_PERIOD_OPTION, render_period_dates
```

- [ ] **Step 3: Repoint imports in `ai_block.py`**

Replace:
```python
from spotify_web.config import get_llm_config

from spotify_web.period_filter import render_period_dates, REPORT_PERIOD_OPTION
```
with:
```python
from spotify_mcp.dashboard.runtime import get_llm_config

from spotify_mcp.dashboard.period_filter import render_period_dates, REPORT_PERIOD_OPTION
```

- [ ] **Step 4: Rewrite `main_page.py` (remove sidebar nav, drop chat)**

Replace the entire file contents with:

```python
"""Streamlit entry point: renders the analytics dashboard (viz + AI report)."""
import streamlit as st

from spotify_core.logging import setup_logging

from spotify_mcp.dashboard.views import render_dashboard

setup_logging()
st.set_page_config(layout="wide", page_title="Spotify Analytics", page_icon="🎵")


def main() -> None:
    st.title("Spotify Analytics")
    render_dashboard()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify no stale references remain in the package**

Run: `git grep -n "spotify_web\|from dashboard import\|from ai_block import\|from chatbot_page import" -- apps/mcp/spotify_mcp/dashboard`
Expected: no output.

- [ ] **Step 6: Smoke-import the importable pages**

Run: `uv run python -c "import spotify_mcp.dashboard.views, spotify_mcp.dashboard.ai_block; print('ok')"`
Expected: prints `ok` (do not import `main_page` directly — it calls `st.set_page_config` at module top).

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add apps/mcp/spotify_mcp/dashboard
git commit -m "refactor(dashboard): move Streamlit pages into spotify_mcp.dashboard, drop chat page"
```

---

### Task 3: Add the `[dashboard]` extra, drop `spotify-web`, delete `apps/web`

**Files:**
- Modify: `apps/mcp/pyproject.toml`
- Modify: `pyproject.toml` (root)
- Delete: `apps/web/` (remaining files)

- [ ] **Step 1: Add the optional extra to `apps/mcp/pyproject.toml`**

After the `[project.entry-points."pipx.run"]` block (and before `[project.urls]`), insert:

```toml
[project.optional-dependencies]
dashboard = [
    "streamlit>=1.35",
    "plotly>=6.0",
    "spotify-analytics-core[report]",
    "langchain-openai>=1.0",
]
```

- [ ] **Step 2: Remove `spotify-web` from the root `pyproject.toml`**

In `pyproject.toml`:
- In `[project] dependencies`, delete the line `    "spotify-web",`.
- In `[tool.uv.workspace] members`, delete the line `    "apps/web",`.
- In `[tool.uv.sources]`, delete the line `spotify-web = { workspace = true }`.

- [ ] **Step 3: Delete the remaining `apps/web` tree**

```bash
git rm -r apps/web
```
Expected removed: `apps/web/__init__.py`, `apps/web/pyproject.toml`, `apps/web/ui/__init__.py`, `apps/web/spotify_web/__init__.py` (the `.py` modules already moved in Tasks 1–2).

- [ ] **Step 4: Re-sync the workspace**

Run: `uv sync`
Expected: resolves with no reference to `spotify-web`; no errors.

- [ ] **Step 5: Confirm no `spotify_web` / `apps/web` references survive in code or tests**

Run: `git grep -n "spotify_web\|apps/web" -- ':!docs' ':!*.md'`
Expected: no output.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp/pyproject.toml pyproject.toml uv.lock
git commit -m "feat(mcp): add [dashboard] extra and retire spotify-web package"
```

---

### Task 4: Add the `dashboard` CLI command

**Files:**
- Modify: `apps/mcp/spotify_mcp/cli.py`
- Test: `tests/mcp/test_cli_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_cli_dashboard.py`:

```python
"""Tests for the `spotify-mcp dashboard` command."""
import subprocess

from typer.testing import CliRunner

import spotify_mcp.cli as cli
from spotify_mcp.cli import app

runner = CliRunner()


def test_dashboard_exits_when_streamlit_missing(monkeypatch):
    monkeypatch.setattr(cli, "_streamlit_available", lambda: False)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 1, result.output
    assert "dashboard" in result.output.lower()


def test_dashboard_launches_streamlit(monkeypatch):
    monkeypatch.setattr(cli, "_streamlit_available", lambda: True)
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["dashboard", "--port", "8600"])
    assert result.exit_code == 0, result.output

    cmd = captured["cmd"]
    assert "-m" in cmd and "streamlit" in cmd and "run" in cmd
    assert cmd[-2:] == ["--server.port", "8600"]
    assert any("main_page.py" in str(part) for part in cmd)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/mcp/test_cli_dashboard.py -q`
Expected: FAIL — `AttributeError: module 'spotify_mcp.cli' has no attribute '_streamlit_available'` / no `dashboard` command.

- [ ] **Step 3: Add the helper + command to `apps/mcp/spotify_mcp/cli.py`**

Near the top of the module (after the existing imports), add:

```python
import importlib.util


def _streamlit_available() -> bool:
    """True when the [dashboard] extra (streamlit) is importable."""
    return importlib.util.find_spec("streamlit") is not None
```

Then add the command (place it next to the other `@app.command()` functions, e.g. before `serve`):

```python
@app.command()
def dashboard(
    port: Annotated[int, typer.Option("--port", help="Port for the Streamlit server.")] = 8501,
) -> None:
    """Launch the Streamlit dashboard (requires the [dashboard] extra)."""
    import subprocess
    import sys
    from importlib.resources import as_file, files

    if not _streamlit_available():
        console.print(
            "[red]Dashboard dependencies are not installed.[/red]\n"
            'Install with:  uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard'
        )
        raise typer.Exit(code=1)

    with as_file(files("spotify_mcp.dashboard") / "main_page.py") as page:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(page), "--server.port", str(port)]
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/mcp/test_cli_dashboard.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify `--help` lists the command**

Run: `uv run spotify-mcp --help`
Expected: output includes `dashboard`.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp/spotify_mcp/cli.py tests/mcp/test_cli_dashboard.py
git commit -m "feat(cli): add dashboard subcommand with [dashboard]-extra guard"
```

---

### Task 5: Gate the LLM/Langfuse wizard steps on `[dashboard]`

**Files:**
- Modify: `apps/mcp/spotify_mcp/wizard/__init__.py`
- Test: `tests/mcp/test_wizard_gating.py`
- Modify: `tests/mcp/test_cli_setup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_gating.py`:

```python
"""The LLM/Langfuse wizard steps run only when the [dashboard] extra is present."""
import spotify_mcp.wizard as wiz


def _mark_all_steps_done(monkeypatch):
    import spotify_mcp.wizard.state as state

    for name in (
        "has_client_id",
        "has_fernet_key",
        "dbs_initialized",
        "tokens_valid",
        "history_has_data",
    ):
        monkeypatch.setattr(state, name, lambda: True)


def _record_steps(monkeypatch, called):
    import spotify_mcp.wizard.claude_desktop as cdk
    import spotify_mcp.wizard.langfuse_keys as lfk
    import spotify_mcp.wizard.llm_keys as lk

    monkeypatch.setattr(lk, "run_step", lambda **k: called.append("llm"))
    monkeypatch.setattr(lfk, "run_step", lambda **k: called.append("langfuse"))
    monkeypatch.setattr(cdk, "run_step", lambda **k: called.append("claude_desktop"))


def test_wizard_skips_llm_steps_without_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    _mark_all_steps_done(monkeypatch)
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: False)
    called: list[str] = []
    _record_steps(monkeypatch, called)

    wiz.run_wizard()

    assert "llm" not in called
    assert "langfuse" not in called
    assert called == ["claude_desktop"]


def test_wizard_runs_llm_steps_with_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    _mark_all_steps_done(monkeypatch)
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: True)
    called: list[str] = []
    _record_steps(monkeypatch, called)

    wiz.run_wizard()

    assert called == ["llm", "langfuse", "claude_desktop"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_gating.py -q`
Expected: FAIL — `AttributeError: module 'spotify_mcp.wizard' has no attribute '_dashboard_installed'`.

- [ ] **Step 3: Add gating to `apps/mcp/spotify_mcp/wizard/__init__.py`**

Add an import and helper near the top (after the existing imports):

```python
import importlib.util


def _dashboard_installed() -> bool:
    """True when the [dashboard] extra (streamlit) is importable."""
    return importlib.util.find_spec("streamlit") is not None
```

In `run_wizard`, replace the two unconditional calls:

```python
    llm_keys.run_step(console=console)
    langfuse_keys.run_step(console=console)
```
with:
```python
    if _dashboard_installed():
        llm_keys.run_step(console=console)
        langfuse_keys.run_step(console=console)
    else:
        console.print("[dim]Install the [dashboard] extra to enable AI reports.[/dim]")
```

- [ ] **Step 4: Run the gating tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_gating.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Make `test_cli_setup.py`'s resume test deterministic**

In `tests/mcp/test_cli_setup.py::test_setup_resumes_when_already_configured`, add this line right after the `import spotify_mcp.wizard.state as state` block (before the `runner.invoke`):

```python
    import spotify_mcp.wizard as wiz
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: True)
```

This keeps the existing assertion `called == ["llm_keys", "langfuse_keys", "claude_desktop"]` valid regardless of whether streamlit is installed in the test environment.

- [ ] **Step 6: Run the setup test**

Run: `uv run pytest tests/mcp/test_cli_setup.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/__init__.py tests/mcp/test_wizard_gating.py tests/mcp/test_cli_setup.py
git commit -m "feat(wizard): gate LLM/Langfuse steps on [dashboard] extra"
```

---

### Task 6: Docs + remove stale scripts

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Delete: `scripts/run_dashboard.bat`, `scripts/run_dashboard.sh`

- [ ] **Step 1: Update `CLAUDE.md` — Repo Layout block**

Replace the `apps/web/` line:
`apps/web/             # spotify-web → src: spotify_web/ + Streamlit UI in apps/web/ui/`
with:
`apps/mcp/             #   spotify_mcp/dashboard/ → Streamlit dashboard (viz + AI report), [dashboard] extra`
(merge into the existing `apps/mcp/` description if cleaner). Then delete the table row:
`| `apps/web/` | `spotify-web` | `spotify_web` |`

- [ ] **Step 2: Update `CLAUDE.md` — Never rule**

Replace:
`- Break existing Streamlit app functionality (it lives in `apps/web/ui/` and must stay runnable)`
with:
`- Break the Streamlit dashboard (it lives in `apps/mcp/spotify_mcp/dashboard/` and must stay runnable via `spotify-mcp dashboard`)`

- [ ] **Step 3: Update `CLAUDE.md` — Imports rule**

Delete the line:
`- `apps/web/` imports from `spotify_core` / `spotify_dataloader` only`

- [ ] **Step 4: Update `CLAUDE.md` — Common Commands**

Replace:
`uv run streamlit run apps/web/ui/main_page.py            # run web dashboard UI`
with:
`uv run spotify-mcp dashboard                             # run the Streamlit dashboard`

- [ ] **Step 5: Mirror the same four edits in `AGENTS.md`**

Apply the equivalent changes wherever `AGENTS.md` mentions `apps/web`, `spotify_web`, `apps/web/ui/`, or the `streamlit run apps/web/ui/main_page.py` command. Then verify:
Run: `git grep -n "apps/web\|spotify_web" -- CLAUDE.md AGENTS.md`
Expected: no output.

- [ ] **Step 6: Delete the stale launcher scripts**

```bash
git rm scripts/run_dashboard.bat scripts/run_dashboard.sh
```

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs: point dashboard at spotify_mcp.dashboard; drop run_dashboard scripts"
```

---

### Task 7: Full verification + smoke

**Files:** none authored.

- [ ] **Step 1: Run the complete suite**

Run: `uv run pytest -q`
Expected: all pass (no regressions; new `test_cli_dashboard` + `test_wizard_gating` included).

- [ ] **Step 2: Confirm the repo is free of the retired names**

Run: `git grep -n "spotify_web\|apps/web" -- ':!docs'`
Expected: no output.

- [ ] **Step 3: CLI smoke — command is registered**

Run: `uv run spotify-mcp dashboard --help`
Expected: exit 0; help text for the `--port` option.

- [ ] **Step 4: CLI smoke — doctor still works**

Run: `uv run spotify-mcp doctor`
Expected: JSON report renders; exit 0 or 1 per readiness.

- [ ] **Step 5 (optional manual): launch the dashboard**

Run: `uv run spotify-mcp dashboard`
Expected: Streamlit starts and serves the dashboard at `http://127.0.0.1:8501`; Ctrl+C to stop. (Skip in non-interactive/CI contexts.)

---

## Notes

- **Why moves keep the suite green mid-refactor:** `pytest` uses `testpaths = tests` (see `pytest.ini`), so the Streamlit pages under `apps/web/ui/` are never collected. Their stale imports between Tasks 1 and 2 don't fail the suite; by Task 3 the directory is gone.
- **Provider coverage:** `langchain-openai` is in the `[dashboard]` extra so the OpenAI report path imports cleanly; core's `[report]` extra is unchanged (decision per spec).
- **`runtime.py` re-exports:** it keeps `from spotify_core.env import get_client_id, get_fernet_key`, so `tests/test_env_load_order.py` can call `runtime.get_client_id()`.
