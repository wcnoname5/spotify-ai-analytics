# Dashboard Integration into the App Package

**Goal:** Make `uvx spotify-mcp dashboard` launch the Streamlit dashboard from a
single published package, with **no separate `spotify-web` package to maintain**.
The dashboard (Plotly visualization + AI report block) becomes part of the
already-published `spotify-analytics-mcp` package, behind an optional
`[dashboard]` extra. The chat/agent page is dropped, and `apps/web/` is deleted.

**Status:** supersedes Tasks 7–8 of
[2026-05-27-unified-cli-config.md](../plans/2026-05-27-unified-cli-config.md).
That plan's Task 9 (`sync --install`) is orthogonal and untouched here.

**Prerequisite — `task-1-6` lands first.** Tasks 1–6 of the unified-cli-config
plan (consolidate env reads into `Settings`; add skippable LLM-key + Langfuse
wizard steps) are already implemented on the `task-1-6` branch. They must be
rebased onto `cli-int`, reviewed, and verified green **before** this refactor,
because `task-1-6` edits the exact files this refactor moves
(`apps/web/spotify_web/config.py` → `dashboard/runtime.py`,
`tests/web/test_web_config.py` → `tests/dashboard/`). Landing it first means the
move carries the consolidated `settings`-based versions instead of colliding on
renamed/deleted files. This becomes **Phase 0** of the implementation plan.

---

## Problem

The dashboard cannot ship via `uvx` today, and not because of "two packages."
The root cause is that **the dashboard UI code is not in any installable package**:

- The `spotify-web` wheel ships only `spotify_web/` — the *helpers* (`charts.py`,
  `config.py`, `formatting.py`, `period_filter.py`).
- The actual Streamlit pages live in `apps/web/ui/` (`main_page.py`,
  `dashboard.py`, `chatbot_page.py`, `ai_block.py`) — a **sibling** of
  `spotify_web/`, **excluded from the wheel**.
- Those pages use bare sibling imports (`from dashboard import render_dashboard`,
  `from ai_block import render_ai_block`) that only resolve because
  `streamlit run apps/web/ui/main_page.py` injects that folder onto `sys.path`.
  They are not importable as a package.

So any solution must move the UI **inside an installed, importable package** and
fix those imports. Given that, the cleanest design is to host the dashboard in the
user-facing app package rather than publish a new `spotify-web` package.

## Decisions (locked)

- **Scope:** viz dashboard **+ AI report block**. The chat/agent page is excluded
  and removed. (Chat can return later as its own extra.)
- **Home for the code:** inside the app package (`spotify_mcp`). No new published
  package.
- **`apps/web/` fate:** deleted entirely; the `spotify-web` package is retired.
- **Launch mechanism:** subprocess — `python -m streamlit run …` (Streamlit's
  public CLI), not the semi-private `streamlit.web.bootstrap`.
- **Helper module rename:** old `spotify_web/config.py` → `runtime.py`;
  old `ui/dashboard.py` → `views.py`.

---

## Target Layout

`apps/web/` is deleted. The shipped UI moves into the app package:

```
apps/mcp/spotify_mcp/
  cli.py                 # + `dashboard` command
  config.py
  _mcp.py, db_crud.py, memory_store.py, spotify_control.py, prompts.py, utils.py
  wizard/ ...
  dashboard/                       # NEW — the whole shipped UI
    __init__.py
    main_page.py                   # entry (was ui/main_page.py); sidebar nav removed entirely
    views.py                       # was ui/dashboard.py   → render_dashboard()
    ai_block.py                    # was ui/ai_block.py    → render_ai_block()
    charts.py                      # was spotify_web/charts.py
    formatting.py                  # was spotify_web/formatting.py
    period_filter.py               # was spotify_web/period_filter.py
    runtime.py                     # was spotify_web/config.py (get_sync_args / get_llm_config)
```

### Import fixes

All bare sibling imports become absolute package imports, e.g.:

- `from dashboard import render_dashboard` → `from spotify_mcp.dashboard.views import render_dashboard`
- `from ai_block import render_ai_block` → `from spotify_mcp.dashboard.ai_block import render_ai_block`
- `from chatbot_page import render_chatbot` → **removed** (chat page dropped)
- `from spotify_web.charts import …` → `from spotify_mcp.dashboard.charts import …`
- `from spotify_web.config import get_sync_args` → `from spotify_mcp.dashboard.runtime import get_sync_args`
- `spotify_core.*` / `spotify_dataloader.*` imports unchanged.

`main_page.py` removes the sidebar navigation entirely and renders only the
dashboard view (the sole remaining page). Because `dashboard/` is now an installed
package, `streamlit run` against the packaged `main_page.py` resolves these imports
in any environment, including `uvx`.

---

## Dependencies / Packaging

### `apps/mcp/pyproject.toml`

```toml
[project.optional-dependencies]
dashboard = [
    "streamlit>=1.35",
    "plotly>=6.0",
    "spotify-analytics-core[report]",   # langchain/langgraph/langfuse for the AI report block
    "langchain-openai>=1.0",            # see provider-coverage note below
]
```

**Provider coverage (decided):** core's `[report]` extra includes
`langchain-google-genai` + `langfuse` but **not** `langchain-openai`, while the
report block (`report/models.py`) and `runtime.get_llm_config()` also offer OpenAI
models. To keep both providers working, `langchain-openai` is added to the
`dashboard` extra (as shown above); core's `[report]` extra is left unchanged.

- **Base install stays MCP-only (lean).** LLM-provider and Langfuse keys are a
  dashboard-only concern, so the setup wizard prompts for them **only when the
  `[dashboard]` extra is installed** — see *Wizard Gating* below.
- Hatchling already ships `spotify_mcp/` recursively, so `dashboard/` and its
  `main_page.py` land in the wheel as ordinary modules — **no extra package-data
  config needed**, and `importlib.resources` can locate `main_page.py`.

### Root `pyproject.toml`

- Remove `spotify-web` from `[tool.uv.workspace] members`.
- Remove `spotify-web` from `[tool.uv.sources]`.
- Remove `spotify-web` from the root `dependencies` list.

### Deleted

- `apps/web/` (entire directory, including `spotify_web/`, `ui/`, its
  `pyproject.toml`, and the chat/agent page `chatbot_page.py`).

---

## `dashboard` CLI Command

`apps/mcp/spotify_mcp/cli.py` — import-guarded, resolves the packaged entry via
`importlib.resources`, shells out to Streamlit:

```python
@app.command()
def dashboard(
    port: Annotated[int, typer.Option("--port", help="Port for the Streamlit server.")] = 8501,
) -> None:
    """Launch the Streamlit dashboard (requires the [dashboard] extra)."""
    import subprocess
    import sys

    try:
        import streamlit  # noqa: F401
    except ImportError:
        console.print(
            '[red]Dashboard dependencies are not installed.[/red]\n'
            'Install with:  uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard'
        )
        raise typer.Exit(code=1)

    from importlib.resources import as_file, files

    with as_file(files("spotify_mcp.dashboard") / "main_page.py") as page:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(page), "--server.port", str(port)]
        )
```

Rationale for subprocess over `streamlit.web.bootstrap`: the `streamlit run` CLI is
the public, version-stable entry; it isolates Streamlit's asyncio/tornado loop,
signal handlers, and logging from the CLI's own loguru/typer setup; an app crash
kills only the child and the CLI returns its exit code.

---

## Wizard Gating (dashboard-only steps)

`task-1-6` adds two skippable wizard steps — `llm_keys.run_step` and
`langfuse_keys.run_step` — but runs them **unconditionally** in `run_wizard`.
Since LLM and Langfuse keys are used *only* by the dashboard's AI report block
(never by the MCP server), an MCP-only install should not prompt for them.

Gate both steps on the dashboard extra being installed:

```python
# apps/mcp/spotify_mcp/wizard/__init__.py
import importlib.util

def _dashboard_installed() -> bool:
    return importlib.util.find_spec("streamlit") is not None

# ... in run_wizard, replacing the two unconditional calls:
    if _dashboard_installed():
        llm_keys.run_step(console=console)
        langfuse_keys.run_step(console=console)
    else:
        console.print("[dim]Install the [dashboard] extra to enable AI reports.[/dim]")
```

`find_spec("streamlit")` is the cleanest signal — `streamlit` ships only with
`[dashboard]`. In a full workspace dev sync it is present, so dev always sees the
steps. Update `tests/mcp/test_cli_setup.py` and add coverage: extra absent ⇒ steps
skipped; extra present ⇒ steps run.

---

## Tests

- Move `tests/web/` → `tests/dashboard/`, repointing imports
  (`spotify_web.*` → `spotify_mcp.dashboard.*`). Affected:
  `test_charts.py`, `test_formatting.py`, `test_period_filter.py`,
  `test_web_config.py` (the last targets `runtime.py` now). Any chat-page test is
  removed.
- New `tests/mcp/test_cli_dashboard.py`:
  - missing `streamlit` (patch the import to raise `ImportError`) ⇒ exit code 1
    and the install hint appears in stdout.
  - `streamlit` present ⇒ `subprocess.run` is invoked (mocked) with a command that
    contains `-m`, `streamlit`, `run`, the resolved `main_page.py` path, and
    `--server.port 8501` (and a custom `--port` is honored).

---

## Docs / Scripts Cleanup

- **CLAUDE.md** — and apply the **same edits to `AGENTS.md`**, which mirrors it:
  - Repo Layout: remove the `apps/web/` line and the `spotify-web` table row; note
    the dashboard lives in `apps/mcp/spotify_mcp/dashboard/`.
  - "Never break the Streamlit app (it lives in `apps/web/ui/`)" rule → rewrite to
    point at `spotify_mcp/dashboard/`.
  - Imports rules: remove the `apps/web/` line.
  - Common Commands: replace `uv run streamlit run apps/web/ui/main_page.py` with
    `uv run spotify-mcp dashboard`.
- **`scripts/run_dashboard.bat` / `run_dashboard.sh`** → **delete** (stale; the
  `spotify-mcp dashboard` command supersedes them).

---

## Out of Scope

- Re-authoring config consolidation / the LLM+Langfuse wizard steps — those arrive
  via the `task-1-6` rebase (Phase 0), not written from scratch here. This spec only
  *gates* the wizard steps (see Wizard Gating).
- `sync --install` Task Scheduler work (Task 9 of the unified-cli-config plan).
- Re-introducing the chat/agent page (future, as its own extra).

## Acceptance

- Phase 0: `task-1-6` rebased onto `cli-int`, reviewed, `uv run pytest` green.
- `uv sync` resolves with `spotify-web` gone and no workspace dangling refs.
- `uv run pytest` green after the test moves + new CLI/wizard-gating tests.
- `uv run spotify-mcp dashboard` launches Streamlit from the packaged
  `main_page.py`; with the extra absent it exits 1 with the install hint.
- Setup wizard skips LLM/Langfuse prompts when `streamlit` is absent, runs them
  when present.
- No remaining references to `spotify_web` or `apps/web` in code, tests, or docs
  (CLAUDE.md **and** AGENTS.md updated; `run_dashboard` scripts deleted).
