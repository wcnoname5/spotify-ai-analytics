# PyPI Packaging & CLI Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "clone + edit `.env` + run `scripts/setup.py` + hand-edit Claude config" install with a single `uv tool install spotify-analytics-mcp && spotify-mcp setup` flow, while keeping the workspace's three packages independently publishable.

**Architecture:** Three packages on PyPI (`spotify-analytics-core`, `spotify-analytics-dataloader`, `spotify-analytics-mcp`). A new `typer`-based `spotify-mcp` CLI lives in `apps/mcp/spotify_mcp/cli.py` and orchestrates the entire one-time setup (Spotify app instructions, port probe, Client-ID prompt, Fernet key generation, DB init, OAuth, optional history import, Claude Desktop config merge). Path resolution moves to `platformdirs` user dirs by default; checkout-mode developers opt in via `SPOTIFY_MCP_DATA_DIR`/`SPOTIFY_MCP_CONFIG_DIR` env vars. The MCP server's lifespan is reduced to `setup_check`-only diagnostics; missing config is surfaced via stderr so Claude Desktop's MCP error UI shows the user what to run.

**Tech Stack:** Python 3.13, `typer`, `rich`, `platformdirs`, `pydantic-settings`, `cryptography.Fernet`, `hatchling`, `uv` workspace, `pytest` + `typer.testing.CliRunner`.

**Spec:** [docs/superpowers/specs/2026-05-05-pypi-packaging-and-cli-setup-design.md](../specs/2026-05-05-pypi-packaging-and-cli-setup-design.md)

---

## File Structure

**New files:**
- `packages/core/spotify_core/paths.py` — single source of truth for config dir, data dir, and `.env` location resolution
- `packages/core/spotify_core/env_file.py` — read/write/upsert keys in a `.env` file with 0600 perms on Unix
- `apps/mcp/spotify_mcp/cli.py` — typer entry point + subcommand wiring
- `apps/mcp/spotify_mcp/wizard/__init__.py`
- `apps/mcp/spotify_mcp/wizard/state.py` — resumability state checks
- `apps/mcp/spotify_mcp/wizard/spotify_app.py` — port probe + dashboard checklist (step 2)
- `apps/mcp/spotify_mcp/wizard/credentials.py` — client-id prompt + Fernet key (steps 3–4)
- `apps/mcp/spotify_mcp/wizard/oauth_step.py` — OAuth wrapper around `spotify_core.spotify_client` (step 6)
- `apps/mcp/spotify_mcp/wizard/history_import.py` — cwd scan + interactive import (step 7)
- `apps/mcp/spotify_mcp/wizard/claude_desktop.py` — config locate / diff / merge (step 8)
- `tests/core/test_paths.py`
- `tests/core/test_env_file.py`
- `tests/mcp/test_cli_setup.py`
- `tests/mcp/test_wizard_state.py`
- `tests/mcp/test_wizard_spotify_app.py`
- `tests/mcp/test_wizard_history_import.py`
- `tests/mcp/test_wizard_claude_desktop.py`

**Modified files:**
- `packages/core/spotify_core/config.py` — replace hardcoded `PROJECT_ROOT/data` with `paths.py` lookups
- `packages/core/pyproject.toml` — add `platformdirs`; rename to `spotify-analytics-core`; add metadata for PyPI
- `packages/dataloader/pyproject.toml` — rename to `spotify-analytics-dataloader`; add metadata
- `apps/mcp/pyproject.toml` — rename to `spotify-analytics-mcp`; add `typer`, `rich`, `platformdirs`; declare `[project.scripts] spotify-mcp`; add metadata
- `apps/mcp/server.py` — drop `_ensure_dbs_initialized`, drop the `setup` MCP tool, write actionable stderr message when config missing
- `apps/mcp/spotify_mcp/config.py` — load env from new resolver

**Files to remove:**
- The `setup` MCP tool block in `apps/mcp/server.py` (lines ~200–228)

---

## Task 1: Path resolver in `spotify_core.paths`

**Files:**
- Create: `packages/core/spotify_core/paths.py`
- Test: `tests/core/test_paths.py`
- Modify: `packages/core/pyproject.toml` (add `platformdirs>=4.0`)

- [ ] **Step 1: Add `platformdirs` to core dependencies**

Edit `packages/core/pyproject.toml`. In the `dependencies = [...]` list add:

```toml
    "platformdirs>=4.0",
```

Run `uv sync` and verify it installs.

- [ ] **Step 2: Write the failing tests**

Create `tests/core/test_paths.py`:

```python
"""Tests for spotify_core.paths — config/data dir resolution."""
import os
from pathlib import Path

import pytest

from spotify_core import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SPOTIFY_MCP_DATA_DIR", raising=False)
    monkeypatch.delenv("SPOTIFY_MCP_CONFIG_DIR", raising=False)


def test_data_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path.resolve()


def test_config_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path.resolve()


def test_data_dir_default_is_platformdirs(monkeypatch):
    # No env override => falls back to platformdirs.user_data_dir
    import platformdirs
    expected = Path(platformdirs.user_data_dir("spotify-mcp")).resolve()
    assert paths.data_dir() == expected


def test_config_dir_default_is_platformdirs(monkeypatch):
    import platformdirs
    expected = Path(platformdirs.user_config_dir("spotify-mcp")).resolve()
    assert paths.config_dir() == expected


def test_env_file_path_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    assert paths.env_file() == (tmp_path / ".env").resolve()


def test_db_paths_live_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    assert paths.history_db() == (tmp_path / "history.db").resolve()
    assert paths.tokens_db() == (tmp_path / "tokens.db").resolve()
    assert paths.ltm_db() == (tmp_path / "ltm.db").resolve()
    assert paths.checkpoints_db() == (tmp_path / "checkpoints.db").resolve()
    assert paths.spotify_history_dir() == (tmp_path / "spotify_history").resolve()


def test_ensure_dirs_creates_missing(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(data))
    paths.ensure_dirs()
    assert cfg.is_dir()
    assert data.is_dir()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spotify_core.paths'`.

- [ ] **Step 4: Implement `paths.py`**

Create `packages/core/spotify_core/paths.py`:

```python
"""Single source of truth for spotify-mcp config and data directory resolution.

Resolution priority (both config_dir and data_dir):
    1. Explicit env var (SPOTIFY_MCP_CONFIG_DIR / SPOTIFY_MCP_DATA_DIR)
    2. platformdirs default (user_config_dir / user_data_dir, app name "spotify-mcp")

Checkout-mode developers opt in by setting the env vars in their shell profile
(e.g. SPOTIFY_MCP_DATA_DIR=$PWD/data, SPOTIFY_MCP_CONFIG_DIR=$PWD).
"""
import os
from pathlib import Path

import platformdirs

_APP_NAME = "spotify-mcp"


def config_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(platformdirs.user_config_dir(_APP_NAME)).resolve()


def data_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(platformdirs.user_data_dir(_APP_NAME)).resolve()


def env_file() -> Path:
    return (config_dir() / ".env").resolve()


def history_db() -> Path:
    return (data_dir() / "history.db").resolve()


def tokens_db() -> Path:
    return (data_dir() / "tokens.db").resolve()


def ltm_db() -> Path:
    return (data_dir() / "ltm.db").resolve()


def checkpoints_db() -> Path:
    return (data_dir() / "checkpoints.db").resolve()


def spotify_history_dir() -> Path:
    return (data_dir() / "spotify_history").resolve()


def ensure_dirs() -> None:
    """Idempotently create config_dir() and data_dir()."""
    config_dir().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_paths.py -v`
Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/core/spotify_core/paths.py tests/core/test_paths.py packages/core/pyproject.toml
git commit -m "feat(core): add paths module for platformdirs-based config/data dirs"
```

---

## Task 2: Refactor `spotify_core.config.Settings` to use `paths.py`

**Files:**
- Modify: `packages/core/spotify_core/config.py`
- Test: extend `tests/core/test_paths.py` with a settings-integration test

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_paths.py`:

```python
def test_settings_picks_up_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    # Force re-import so module-level `settings` re-resolves
    import importlib

    import spotify_core.config as cfg
    importlib.reload(cfg)

    assert cfg.settings.history_db_path == (tmp_path / "history.db").resolve()
    assert cfg.settings.tokens_db_path == (tmp_path / "tokens.db").resolve()
    assert cfg.settings.ltm_db_path == (tmp_path / "ltm.db").resolve()
    assert cfg.settings.spotify_data_path == (tmp_path / "spotify_history").resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_paths.py::test_settings_picks_up_data_dir_override -v`
Expected: FAIL — current `Settings` defaults are pinned to `PROJECT_ROOT/data`, not the env-var override.

- [ ] **Step 3: Replace `config.py`**

Rewrite `packages/core/spotify_core/config.py` to:

```python
import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from spotify_core import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(paths.env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Model Configuration
    use_gemini: bool = Field(default=True, alias="USE_GEMINI")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    openai_model: str = Field(default="gpt-4", alias="OPENAI_MODEL")

    # Data paths — defaults flow through paths.py so platformdirs / env override
    # both work without touching this class.
    spotify_data_path: Path = Field(default_factory=paths.spotify_history_dir, alias="SPOTIFY_DATA_PATH")
    spotify_user_id: str = Field(default="default", alias="SPOTIFY_USER_ID")

    history_db_path: Path = Field(default_factory=paths.history_db, alias="HISTORY_DB_PATH")
    tokens_db_path: Path = Field(default_factory=paths.tokens_db, alias="TOKENS_DB_PATH")
    ltm_db_path: Path = Field(default_factory=paths.ltm_db, alias="LTM_DB_PATH")
    checkpoints_db_path: Path = Field(default_factory=paths.checkpoints_db, alias="CHECKPOINTS_DB_PATH")

    @field_validator(
        "spotify_data_path",
        "history_db_path",
        "tokens_db_path",
        "ltm_db_path",
        "checkpoints_db_path",
        mode="before",
    )
    @classmethod
    def resolve_path(cls, v: str | Path) -> Path:
        if isinstance(v, str):
            path = Path(v).expanduser()
            if not path.is_absolute():
                # Relative paths resolve against the data dir, not cwd, so behavior
                # is stable regardless of where the user invoked the command from.
                return (paths.data_dir() / path).resolve()
            return path.resolve()
        return v

    def validate_paths(self):
        logger = logging.getLogger(__name__)
        if not self.spotify_data_path.exists():
            logger.warning("SPOTIFY_DATA_PATH not found: %s", self.spotify_data_path)
            logger.warning("Place your Streaming_History_Audio_*.json files there.")
        else:
            logger.info("Spotify history data path verified: %s", self.spotify_data_path)


settings = Settings()
```

- [ ] **Step 4: Run all core tests**

Run: `uv run pytest tests/core/ -v`
Expected: all pass.

- [ ] **Step 5: Run the full suite to catch fallout**

Run: `uv run pytest -v`
Expected: pass. If any test was importing `PROJECT_ROOT` from `config.py`, fix the import to use `paths` instead, then re-run.

- [ ] **Step 6: Commit**

```bash
git add packages/core/spotify_core/config.py tests/core/test_paths.py
git commit -m "refactor(core): route Settings paths through paths.py"
```

---

## Task 3: `.env` file helper

**Files:**
- Create: `packages/core/spotify_core/env_file.py`
- Test: `tests/core/test_env_file.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_env_file.py`:

```python
"""Tests for spotify_core.env_file — read/upsert keys in a .env file."""
import os
import sys
from pathlib import Path

import pytest

from spotify_core import env_file as ef


def test_read_key_returns_none_when_file_missing(tmp_path):
    assert ef.read_key(tmp_path / ".env", "FOO") is None


def test_read_key_returns_value_when_present(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\nBAZ=qux\n")
    assert ef.read_key(p, "FOO") == "bar"
    assert ef.read_key(p, "BAZ") == "qux"


def test_read_key_strips_quotes_and_whitespace(tmp_path):
    p = tmp_path / ".env"
    p.write_text('  FOO = "bar baz"  \n')
    assert ef.read_key(p, "FOO") == "bar baz"


def test_upsert_creates_file_when_missing(tmp_path):
    p = tmp_path / ".env"
    ef.upsert(p, "FOO", "bar")
    assert p.read_text().strip() == "FOO=bar"


def test_upsert_replaces_existing_key(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=old\nBAZ=qux\n")
    ef.upsert(p, "FOO", "new")
    text = p.read_text()
    assert "FOO=new" in text
    assert "FOO=old" not in text
    assert "BAZ=qux" in text  # other keys preserved


def test_upsert_appends_when_key_missing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("BAZ=qux\n")
    ef.upsert(p, "FOO", "bar")
    text = p.read_text()
    assert "BAZ=qux" in text
    assert "FOO=bar" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only chmod check")
def test_upsert_sets_0600_on_unix(tmp_path):
    p = tmp_path / ".env"
    ef.upsert(p, "FOO", "bar")
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_env_file.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `env_file.py`**

Create `packages/core/spotify_core/env_file.py`:

```python
"""Tiny .env reader/writer used by the CLI setup wizard.

Why not python-dotenv? We need an upsert-with-perms primitive that doesn't
shell-escape values or care about comments. python-dotenv's `set_key` is
close but doesn't apply 0600 and forces quote handling we don't want.
"""
import os
import re
import sys
from pathlib import Path
from typing import Optional

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _strip_value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        return raw[1:-1]
    return raw


def read_key(path: Path, key: str) -> Optional[str]:
    """Return the value of ``key`` from a .env file, or None if missing."""
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line)
        if m and m.group(1) == key:
            return _strip_value(m.group(2))
    return None


def upsert(path: Path, key: str, value: str) -> None:
    """Insert or replace ``key=value`` in a .env file, creating it if missing.

    On Unix, sets file permissions to 0600 after writing. On Windows, relies
    on the user-profile ACL inherited from the parent directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    new_line = f"{key}={value}"

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        replaced = False
        for i, line in enumerate(lines):
            m = _LINE_RE.match(line)
            if m and m.group(1) == key:
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.write_text(new_line + "\n", encoding="utf-8")

    if sys.platform != "win32":
        os.chmod(path, 0o600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_env_file.py -v`
Expected: all 7 tests pass (skipif on Windows).

- [ ] **Step 5: Commit**

```bash
git add packages/core/spotify_core/env_file.py tests/core/test_env_file.py
git commit -m "feat(core): add env_file upsert helper with 0600 perms"
```

---

## Task 4: CLI skeleton + entry point

**Files:**
- Create: `apps/mcp/spotify_mcp/cli.py`
- Modify: `apps/mcp/pyproject.toml` (add deps + `[project.scripts]`)
- Test: `tests/mcp/test_cli_setup.py`

- [ ] **Step 1: Add CLI deps and entry point**

Edit `apps/mcp/pyproject.toml`:

```toml
[project]
name = "spotify-mcp"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastmcp>=2.0",
    "spotify-core",
    "spotify-dataloader",
    "typer>=0.12",
    "rich>=13.7",
    "platformdirs>=4.0",
]

[project.scripts]
spotify-mcp = "spotify_mcp.cli:app"

[tool.uv.sources]
spotify-core = { workspace = true }
spotify-dataloader = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["spotify_mcp"]
```

Run `uv sync`.

- [ ] **Step 2: Write the failing test**

Create `tests/mcp/test_cli_setup.py`:

```python
"""Tests for the spotify-mcp CLI."""
from typer.testing import CliRunner

from spotify_mcp.cli import app


runner = CliRunner()


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("setup", "doctor", "reauth"):
        assert cmd in result.stdout


def test_doctor_runs_without_args():
    result = runner.invoke(app, ["doctor"])
    # We don't care if the report says "ready" — only that the command wires up.
    assert result.exit_code in (0, 1)
```

Also create `tests/mcp/__init__.py` (empty) if it doesn't exist.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_cli_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: spotify_mcp.cli`.

- [ ] **Step 4: Create CLI skeleton**

Create `apps/mcp/spotify_mcp/cli.py`:

```python
"""spotify-mcp CLI: one-time setup, diagnostics, and re-auth."""
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="spotify-mcp",
    help="Setup and diagnostics for the Spotify Analytics MCP server.",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context):
    """When invoked with no subcommand, run `setup`."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(setup)


@app.command()
def setup(
    install_claude_desktop: bool = typer.Option(
        False, "--install-claude-desktop", help="Also write the Claude Desktop config entry."
    ),
    import_path: Optional[Path] = typer.Option(
        None, "--import", help="Skip wizard; import a Spotify JSON export from this path."
    ),
):
    """Run the first-run setup wizard, or resume from a partial run."""
    from spotify_mcp.wizard import run_wizard

    run_wizard(
        install_claude_desktop=install_claude_desktop,
        import_path=import_path,
        console=console,
    )


@app.command()
def doctor():
    """Print a diagnostic report (same as the in-Claude `setup_check` tool)."""
    from spotify_mcp.wizard.state import collect_report

    report = collect_report()
    console.print_json(data=report)
    raise typer.Exit(code=0 if report["ready"] else 1)


@app.command()
def reauth():
    """Re-run only the OAuth browser flow (recovery)."""
    from spotify_mcp.wizard.oauth_step import run_oauth

    run_oauth(console=console, force=True)
```

Create `apps/mcp/spotify_mcp/wizard/__init__.py`:

```python
"""Setup wizard package — orchestrates the resumable steps in cli.py."""
from pathlib import Path
from typing import Optional

from rich.console import Console


def run_wizard(
    install_claude_desktop: bool,
    import_path: Optional[Path],
    console: Console,
) -> None:
    """Wired up in Task 13 once all wizard steps exist."""
    raise NotImplementedError("wizard not implemented yet")
```

Create `apps/mcp/spotify_mcp/wizard/state.py` (stub for Task 5):

```python
"""Resumability state checks. Filled out in Task 5."""
def collect_report() -> dict:
    return {"ready": False, "checks": {}, "actions_needed": ["wizard not implemented"], "message": "stub"}
```

Create `apps/mcp/spotify_mcp/wizard/oauth_step.py` (stub for Task 10):

```python
"""OAuth wizard step. Filled out in Task 10."""
from rich.console import Console


def run_oauth(console: Console, force: bool = False) -> None:
    raise NotImplementedError("oauth step not implemented yet")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_cli_setup.py -v`
Expected: `test_help_lists_all_subcommands` passes; `test_doctor_runs_without_args` passes (exits 1 with stub report).

- [ ] **Step 6: Verify entry point is registered**

Run: `uv run spotify-mcp --help`
Expected: typer help screen lists `setup`, `doctor`, `reauth`.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp/spotify_mcp/cli.py apps/mcp/spotify_mcp/wizard apps/mcp/pyproject.toml tests/mcp/__init__.py tests/mcp/test_cli_setup.py
git commit -m "feat(mcp): add typer CLI skeleton with setup/doctor/reauth subcommands"
```

---

## Task 5: Resumability state checks

**Files:**
- Modify: `apps/mcp/spotify_mcp/wizard/state.py`
- Test: `tests/mcp/test_wizard_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_state.py`:

```python
"""Tests for wizard.state — resumability checks."""
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from spotify_mcp.wizard import state as st


@pytest.fixture
def temp_install(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    cfg.mkdir()
    data.mkdir()
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(data))
    # Force a clean import so paths re-resolve
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    return cfg, data


def test_no_client_id_when_env_missing(temp_install, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    cfg, _ = temp_install
    assert st.has_client_id() is False


def test_has_client_id_reads_from_env_file(temp_install):
    cfg, _ = temp_install
    (cfg / ".env").write_text("SPOTIFY_CLIENT_ID=abc123\n")
    assert st.has_client_id() is True


def test_has_fernet_key_reads_from_env_file(temp_install):
    cfg, _ = temp_install
    (cfg / ".env").write_text(f"TOKEN_ENCRYPT_KEY={Fernet.generate_key().decode()}\n")
    assert st.has_fernet_key() is True


def test_dbs_initialized_false_when_missing(temp_install):
    assert st.dbs_initialized() is False


def test_dbs_initialized_true_after_init(temp_install):
    from spotify_core.db.migrations import init_history_db, init_ltm_db, init_tokens_db
    from spotify_core import paths

    init_history_db(paths.history_db())
    init_tokens_db(paths.tokens_db())
    init_ltm_db(paths.ltm_db())
    assert st.dbs_initialized() is True


def test_tokens_valid_false_when_no_row(temp_install):
    from spotify_core.db.migrations import init_tokens_db
    from spotify_core import paths

    init_tokens_db(paths.tokens_db())
    assert st.tokens_valid() is False


def test_collect_report_lists_all_checks(temp_install):
    report = st.collect_report()
    assert set(report["checks"].keys()) >= {
        "client_id", "fernet_key", "dbs_initialized", "tokens_valid"
    }
    assert isinstance(report["actions_needed"], list)
    assert isinstance(report["ready"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_state.py -v`
Expected: most fail (stub `collect_report` returns the placeholder).

- [ ] **Step 3: Implement state checks**

Replace `apps/mcp/spotify_mcp/wizard/state.py` with:

```python
"""Resumability state checks for the setup wizard.

Each check reads the *current* state from disk/env and returns a bool. Used by
the wizard to skip already-completed steps and by `spotify-mcp doctor`.
"""
import os
from pathlib import Path

from spotify_core import env_file, paths


def _client_id_value() -> str:
    """Prefer process env, fall back to <config_dir>/.env."""
    val = os.environ.get("SPOTIFY_CLIENT_ID")
    if val:
        return val
    return env_file.read_key(paths.env_file(), "SPOTIFY_CLIENT_ID") or ""


def _fernet_key_value() -> str:
    val = os.environ.get("TOKEN_ENCRYPT_KEY")
    if val:
        return val
    return env_file.read_key(paths.env_file(), "TOKEN_ENCRYPT_KEY") or ""


def has_client_id() -> bool:
    return bool(_client_id_value().strip())


def has_fernet_key() -> bool:
    return bool(_fernet_key_value().strip())


def dbs_initialized() -> bool:
    """Both history and tokens DBs exist with a known table."""
    import sqlite3

    for db_path, table in (
        (paths.history_db(), "listening_history"),
        (paths.tokens_db(), "spotify_tokens"),
    ):
        if not db_path.exists():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
        except sqlite3.Error:
            return False
    return paths.ltm_db().exists()


def tokens_valid() -> bool:
    """Tokens row exists for the default user, decrypts cleanly, and has a refresh_token.

    Does NOT check expiry of the access token (refresh handles that at runtime)
    and does NOT ping Spotify (slow, network-dependent).
    """
    if not has_fernet_key():
        return False
    if not paths.tokens_db().exists():
        return False
    try:
        from spotify_core.config import settings
        from spotify_core.spotify_client.token_store import load_tokens

        tokens = load_tokens(
            paths.tokens_db(),
            settings.spotify_user_id,
            _fernet_key_value().encode(),
        )
        return bool(tokens and tokens.get("refresh_token"))
    except Exception:
        return False


def history_has_data() -> bool:
    import sqlite3

    if not paths.history_db().exists():
        return False
    try:
        with sqlite3.connect(paths.history_db()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def collect_report() -> dict:
    """Build a `setup_check`-style report from the live filesystem state."""
    checks = {
        "client_id": has_client_id(),
        "fernet_key": has_fernet_key(),
        "dbs_initialized": dbs_initialized(),
        "tokens_valid": tokens_valid(),
        "history_has_data": history_has_data(),
    }
    actions: list[str] = []
    if not checks["client_id"]:
        actions.append("Set SPOTIFY_CLIENT_ID — run `spotify-mcp setup`")
    if not checks["fernet_key"]:
        actions.append("Generate TOKEN_ENCRYPT_KEY — run `spotify-mcp setup`")
    if not checks["dbs_initialized"]:
        actions.append("Initialize databases — run `spotify-mcp setup`")
    if not checks["tokens_valid"]:
        actions.append("Authorize with Spotify — run `spotify-mcp setup` (or `spotify-mcp reauth`)")
    if checks["dbs_initialized"] and not checks["history_has_data"]:
        actions.append(
            "Load history — run `spotify-mcp setup` (option 1: import full export, "
            "or option 2: sync recent 50 plays)"
        )

    return {
        "ready": len(actions) == 0 or actions == [
            a for a in actions if "Load history" in a
        ],
        "checks": checks,
        "actions_needed": actions,
        "message": "All set." if not actions else f"{len(actions)} action(s) required.",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_state.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/state.py tests/mcp/test_wizard_state.py
git commit -m "feat(mcp): implement resumability state checks for wizard"
```

---

## Task 6: Spotify-app step (port probe + dashboard checklist)

**Files:**
- Create: `apps/mcp/spotify_mcp/wizard/spotify_app.py`
- Test: `tests/mcp/test_wizard_spotify_app.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_spotify_app.py`:

```python
"""Tests for the Spotify-app wizard step (port probe + dashboard checklist)."""
import socket

import pytest
from rich.console import Console

from spotify_mcp.wizard import spotify_app


def test_port_available_returns_true_when_free(monkeypatch):
    # Pick a port we know is unbound: bind ephemeral, free it, ask.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert spotify_app.port_available(port) is True


def test_port_available_returns_false_when_bound():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert spotify_app.port_available(port) is False
    finally:
        s.close()


def test_run_step_aborts_when_port_in_use(monkeypatch):
    monkeypatch.setattr(spotify_app, "port_available", lambda p: False)
    console = Console(record=True, width=120)
    with pytest.raises(spotify_app.PortInUseError):
        spotify_app.run_step(console=console, port=spotify_app.OAUTH_PORT)


def test_run_step_prints_checklist_when_port_free(monkeypatch):
    monkeypatch.setattr(spotify_app, "port_available", lambda p: True)
    monkeypatch.setattr(spotify_app, "_open_browser", lambda url: None)
    console = Console(record=True, width=120)
    spotify_app.run_step(console=console, port=spotify_app.OAUTH_PORT)
    output = console.export_text()
    assert "Create app" in output
    assert "http://127.0.0.1:8888/callback" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_spotify_app.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `spotify_app.py`**

Create `apps/mcp/spotify_mcp/wizard/spotify_app.py`:

```python
"""Wizard step: probe OAuth port, then walk the user through Spotify app registration."""
import socket
import webbrowser
from contextlib import closing

from rich.console import Console
from rich.panel import Panel

OAUTH_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{OAUTH_PORT}/callback"
DASHBOARD_URL = "https://developer.spotify.com/dashboard"


class PortInUseError(RuntimeError):
    """Raised when the OAuth port is already bound."""


def port_available(port: int) -> bool:
    """True if 127.0.0.1:port can be bound right now."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _open_browser(url: str) -> None:
    webbrowser.open(url)


_CHECKLIST = """
[bold]In the Spotify dashboard:[/bold]
  1. Click [bold]Create app[/bold]
  2. Enter any name and description
  3. [bold]Redirect URI:[/bold] paste this exact value, then click [bold]Add[/bold]:
       [cyan]{redirect_uri}[/cyan]
  4. API/SDK: tick [bold]Web API[/bold]
  5. Accept the Terms of Service, click [bold]Save[/bold]
  6. Open the app's [bold]Settings[/bold] page and copy the [bold]Client ID[/bold]
"""


def run_step(console: Console, port: int = OAUTH_PORT) -> None:
    """Probe the OAuth port and print the dashboard checklist.

    Raises:
        PortInUseError: if the port is already bound.
    """
    if not port_available(port):
        raise PortInUseError(
            f"Port {port} is already in use. Free it before continuing.\n"
            f"  Common causes: another spotify-mcp setup in progress, a Docker container, "
            f"a local web server.\n"
            f"  Find what's bound: lsof -i :{port}  (Unix)  /  netstat -ano | findstr :{port}  (Windows)"
        )

    console.print(Panel.fit(
        f"Opening the Spotify Developer Dashboard at\n  [cyan]{DASHBOARD_URL}[/cyan]",
        title="Step 1 / 6: Register your Spotify app",
    ))
    _open_browser(DASHBOARD_URL)
    console.print(_CHECKLIST.format(redirect_uri=REDIRECT_URI))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_spotify_app.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/spotify_app.py tests/mcp/test_wizard_spotify_app.py
git commit -m "feat(mcp): wizard step — port probe + Spotify app checklist"
```

---

## Task 7: Credentials step (Client ID + Fernet key)

**Files:**
- Create: `apps/mcp/spotify_mcp/wizard/credentials.py`
- Test: `tests/mcp/test_wizard_credentials.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_credentials.py`:

```python
"""Tests for wizard.credentials — client_id and Fernet key persistence."""
import os
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import credentials


@pytest.fixture
def temp_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    return tmp_path


def test_persist_client_id_writes_env(temp_cfg):
    credentials.persist_client_id("abc123def456")
    env = (temp_cfg / ".env").read_text()
    assert "SPOTIFY_CLIENT_ID=abc123def456" in env


def test_persist_client_id_strips_whitespace(temp_cfg):
    credentials.persist_client_id("  abc123  ")
    env = (temp_cfg / ".env").read_text()
    assert "SPOTIFY_CLIENT_ID=abc123" in env


def test_persist_client_id_rejects_empty(temp_cfg):
    with pytest.raises(ValueError):
        credentials.persist_client_id("")


def test_ensure_fernet_key_creates_when_missing(temp_cfg):
    console = Console(record=True)
    key = credentials.ensure_fernet_key(console=console)
    from cryptography.fernet import Fernet
    Fernet(key.encode())  # must round-trip as a valid key


def test_ensure_fernet_key_skips_when_present(temp_cfg):
    from cryptography.fernet import Fernet
    existing = Fernet.generate_key().decode()
    (temp_cfg / ".env").write_text(f"TOKEN_ENCRYPT_KEY={existing}\n")
    console = Console(record=True)
    key = credentials.ensure_fernet_key(console=console)
    assert key == existing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_credentials.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `credentials.py`**

Create `apps/mcp/spotify_mcp/wizard/credentials.py`:

```python
"""Wizard steps: persist Client ID and ensure a Fernet key exists."""
import os

from cryptography.fernet import Fernet
from rich.console import Console

from spotify_core import env_file, paths


def persist_client_id(raw: str) -> None:
    """Trim, validate non-empty, warn (don't reject) on suspicious shape, persist."""
    value = raw.strip()
    if not value:
        raise ValueError("Client ID must not be empty.")
    env_file.upsert(paths.env_file(), "SPOTIFY_CLIENT_ID", value)
    os.environ["SPOTIFY_CLIENT_ID"] = value


def looks_like_client_id(value: str) -> bool:
    """Soft heuristic: 32-char hex. False is a warning, not a rejection."""
    return len(value) == 32 and all(c in "0123456789abcdef" for c in value.lower())


def prompt_client_id(console: Console) -> str:
    """Prompt the user for their Client ID and persist it. Returns the value."""
    while True:
        value = console.input("[bold]Paste your Spotify Client ID:[/bold] ").strip()
        if not value:
            console.print("[red]Client ID is required.[/red]")
            continue
        if not looks_like_client_id(value):
            console.print(
                "[yellow]Heads up — that doesn't look like the usual 32-char hex Client ID, "
                "but proceeding anyway. If OAuth fails, double-check the value.[/yellow]"
            )
        persist_client_id(value)
        return value


def ensure_fernet_key(console: Console) -> str:
    """Read existing TOKEN_ENCRYPT_KEY, or generate one and persist.

    Never overwrites an existing key — regenerating would orphan all stored tokens.
    """
    existing = env_file.read_key(paths.env_file(), "TOKEN_ENCRYPT_KEY")
    if existing:
        os.environ["TOKEN_ENCRYPT_KEY"] = existing
        return existing
    new_key = Fernet.generate_key().decode()
    env_file.upsert(paths.env_file(), "TOKEN_ENCRYPT_KEY", new_key)
    os.environ["TOKEN_ENCRYPT_KEY"] = new_key
    console.print(
        f"[yellow]Generated a new encryption key and saved it to {paths.env_file()}.\n"
        "Do NOT delete this file — losing the key makes stored tokens unrecoverable.[/yellow]"
    )
    return new_key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_credentials.py -v`
Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/credentials.py tests/mcp/test_wizard_credentials.py
git commit -m "feat(mcp): wizard step — Client ID prompt and Fernet key bootstrap"
```

---

## Task 8: OAuth wizard step

**Files:**
- Modify: `apps/mcp/spotify_mcp/wizard/oauth_step.py`
- Test: `tests/mcp/test_wizard_oauth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_wizard_oauth.py`:

```python
"""Tests for wizard.oauth_step — wraps spotify_core.spotify_client PKCE flow."""
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console

from spotify_mcp.wizard import oauth_step


@pytest.fixture
def temp_install(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", Fernet.generate_key().decode())
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    from spotify_core.db.migrations import init_tokens_db
    init_tokens_db(p.tokens_db())
    return tmp_path


def test_run_oauth_skips_when_tokens_valid_and_not_forced(temp_install, monkeypatch):
    monkeypatch.setattr(
        "spotify_mcp.wizard.state.tokens_valid", lambda: True
    )
    called = {"flag": False}

    def _stub(**kwargs):
        called["flag"] = True
        return {}

    monkeypatch.setattr("spotify_core.spotify_client.auth.run_pkce_flow", _stub)
    oauth_step.run_oauth(console=Console(), force=False)
    assert called["flag"] is False


def test_run_oauth_invokes_pkce_and_saves_tokens(temp_install, monkeypatch):
    monkeypatch.setattr("spotify_mcp.wizard.state.tokens_valid", lambda: False)
    monkeypatch.setattr(
        "spotify_core.spotify_client.auth.run_pkce_flow",
        lambda **_: {
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 3600,
            "scope": "user-read-recently-played",
        },
    )
    oauth_step.run_oauth(console=Console(), force=False)

    from spotify_core import paths
    from spotify_core.spotify_client.token_store import load_tokens
    tokens = load_tokens(
        paths.tokens_db(),
        "default",
        os.environ["TOKEN_ENCRYPT_KEY"].encode(),
    )
    assert tokens is not None
    assert tokens["refresh_token"] == "RT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_wizard_oauth.py -v`
Expected: FAIL — `oauth_step.run_oauth` raises `NotImplementedError`.

- [ ] **Step 3: Implement `oauth_step.py`**

Replace `apps/mcp/spotify_mcp/wizard/oauth_step.py`:

```python
"""Wizard step: run the OAuth PKCE flow and store encrypted tokens."""
import os

from rich.console import Console

from spotify_core import paths
from spotify_core.config import settings
from spotify_core.spotify_client.auth import run_pkce_flow
from spotify_core.spotify_client.token_store import save_tokens

from spotify_mcp.wizard import state, spotify_app


def run_oauth(console: Console, force: bool = False) -> None:
    """Run the PKCE flow if needed; persist encrypted tokens to tokens.db.

    Skips when ``state.tokens_valid()`` is True and ``force`` is False.
    """
    if not force and state.tokens_valid():
        console.print("[green]Existing Spotify tokens are valid — skipping OAuth.[/green]")
        return

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    fernet_key = os.environ.get("TOKEN_ENCRYPT_KEY", "").strip()
    if not client_id:
        raise RuntimeError("SPOTIFY_CLIENT_ID not set — run earlier wizard steps first.")
    if not fernet_key:
        raise RuntimeError("TOKEN_ENCRYPT_KEY not set — run earlier wizard steps first.")

    console.print(f"[bold]Opening browser for Spotify login...[/bold]")
    token_data = run_pkce_flow(client_id=client_id, port=spotify_app.OAUTH_PORT)
    save_tokens(paths.tokens_db(), settings.spotify_user_id, token_data, fernet_key.encode())
    console.print("[green]Spotify authorization complete.[/green]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_wizard_oauth.py -v`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/oauth_step.py tests/mcp/test_wizard_oauth.py
git commit -m "feat(mcp): wizard step — OAuth PKCE wrapper"
```

---

## Task 9: History import step

**Files:**
- Create: `apps/mcp/spotify_mcp/wizard/history_import.py`
- Test: `tests/mcp/test_wizard_history_import.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_history_import.py`:

```python
"""Tests for wizard.history_import — GUI picker with cwd-scan fallback."""
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import history_import as hi


def test_scan_dir_finds_streaming_files(tmp_path):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    (tmp_path / "Streaming_History_Audio_2024.json").write_text("[]")
    (tmp_path / "other.json").write_text("[]")
    found = hi.scan_dir(tmp_path)
    assert len(found) == 2
    assert all(p.name.startswith("Streaming_History_Audio_") for p in found)


def test_scan_dir_returns_empty_when_no_match(tmp_path):
    assert hi.scan_dir(tmp_path) == []


def test_pick_dir_via_gui_returns_none_when_tkinter_unavailable(monkeypatch):
    # Simulate "no GUI" by making the GUI helper raise.
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: (_ for _ in ()).throw(RuntimeError("no display")))
    assert hi.pick_dir_via_gui() is None


def test_pick_dir_via_gui_returns_none_when_user_cancels(monkeypatch):
    # askdirectory returns "" when the user cancels.
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: "")
    assert hi.pick_dir_via_gui() is None


def test_pick_dir_via_gui_returns_path_when_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: str(tmp_path))
    assert hi.pick_dir_via_gui() == tmp_path


def test_run_step_skip_choice_does_nothing(monkeypatch):
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "skip")
    called = {"import": False, "sync": False}
    monkeypatch.setattr(hi, "_do_import", lambda console, files: called.__setitem__("import", True))
    monkeypatch.setattr(hi, "_do_sync_recent", lambda console: called.__setitem__("sync", True))
    hi.run_step(console=Console(record=True))
    assert called == {"import": False, "sync": False}


def test_run_step_import_uses_gui_when_available(tmp_path, monkeypatch):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: tmp_path)
    captured = {}
    monkeypatch.setattr(hi, "_do_import", lambda console, files: captured.update(files=files))
    hi.run_step(console=Console(record=True))
    assert len(captured["files"]) == 1


def test_run_step_falls_back_to_cwd_scan_when_gui_unavailable(tmp_path, monkeypatch):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: None)  # GUI unavailable / cancelled
    monkeypatch.setattr(hi, "_confirm_use_cwd", lambda console, files: True)
    captured = {}
    monkeypatch.setattr(hi, "_do_import", lambda console, files: captured.update(files=files))
    hi.run_step(console=Console(record=True))
    assert len(captured["files"]) == 1


def test_run_step_skips_when_gui_cancelled_and_cwd_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: None)
    called = {"import": False}
    monkeypatch.setattr(hi, "_do_import", lambda console, files: called.__setitem__("import", True))
    hi.run_step(console=Console(record=True))
    assert called["import"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_history_import.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `history_import.py`**

Create `apps/mcp/spotify_mcp/wizard/history_import.py`:

```python
"""Wizard step: optional history import.

UX rule: never make the user type a path. Primary UX is a native folder
picker (tkinter filedialog). On headless systems where Tk can't open a
window, falls back to scanning cwd. Power users can pass
`spotify-mcp setup --import <path>` to skip the prompt entirely.
"""
import os
from pathlib import Path
from typing import Literal, Optional

from rich.console import Console
from rich.panel import Panel

from spotify_core import paths


_REQUEST_BANNER = (
    "[bold]Recommended:[/bold] request your full Spotify listening history from Spotify Privacy.\n"
    "It contains years of plays vs. only the last 50 from the live API.\n"
    "Request at https://www.spotify.com/account/privacy/ — arrives by email in ~5 days."
)


def scan_dir(directory: Path) -> list[Path]:
    """Return all Streaming_History_Audio_*.json files in a directory (non-recursive)."""
    return sorted(Path(directory).glob("Streaming_History_Audio_*.json"))


def _tk_askdirectory() -> str:
    """Open a native folder-picker dialog. Returns the selected path or "" if cancelled.

    Isolated for monkeypatching. Raises whatever tkinter raises if Tk cannot
    be initialised (e.g. no DISPLAY) — caller is expected to handle.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # hide the empty root window
    try:
        return filedialog.askdirectory(title="Select your Spotify history export folder")
    finally:
        root.destroy()


def pick_dir_via_gui() -> Optional[Path]:
    """Try to open the GUI folder picker. Returns the selected Path, or None on:

    - tkinter import failure (missing _tkinter)
    - Tk init failure (no display, no X server)
    - user cancellation (askdirectory returns "")
    """
    try:
        selected = _tk_askdirectory()
    except Exception:
        return None
    if not selected:
        return None
    return Path(selected)


def _prompt_choice(console: Console) -> Literal["import", "sync", "skip"]:
    console.print(
        "\n[bold]Choose history source:[/bold]\n"
        "  [1] Import a Spotify JSON export (opens folder picker)\n"
        "  [2] Sync the most recent 50 plays from the live API (instant, partial)\n"
        "  [3] Skip — I'll do this later"
    )
    while True:
        choice = console.input("Select [1/2/3]: ").strip()
        if choice == "1":
            return "import"
        if choice == "2":
            return "sync"
        if choice == "3":
            return "skip"
        console.print("[red]Please enter 1, 2, or 3.[/red]")


def _confirm_use_cwd(console: Console, files: list[Path]) -> bool:
    if not files:
        console.print(
            "[yellow]GUI picker unavailable and no Streaming_History_Audio_*.json files in the "
            "current directory. Drop the files into the current folder (or `cd` to where they are) "
            "and re-run `spotify-mcp setup`. Or use `spotify-mcp setup --import <path>` directly."
            "[/yellow]"
        )
        return False
    console.print(
        f"[yellow]GUI picker unavailable. Found {len(files)} file(s) in the current directory:[/yellow]"
    )
    for f in files:
        console.print(f"  • {f.name}")
    answer = console.input("Import these? [y/N] ").strip().lower()
    return answer == "y"


def _do_import(console: Console, files: list[Path]) -> None:
    from spotify_core.db.pipeline import import_json_to_db

    if not files:
        return

    directory = files[0].parent
    console.print(f"Importing {len(files)} file(s) from {directory} into {paths.history_db()}...")
    result = import_json_to_db(str(directory), str(paths.history_db()))
    console.print(
        f"[green]Imported {result['inserted']} rows.[/green]  "
        f"Duplicates skipped: {result['skipped_duplicated']}, "
        f"parse errors: {result['skipped_parse_error']}"
    )


def _do_sync_recent(console: Console) -> None:
    """Sync the last 50 plays via the Spotify API."""
    from spotify_core.config import settings
    from spotify_core.db.pipeline import init_history_db
    from spotify_core.spotify_client.client import SpotifyClient

    init_history_db(str(paths.history_db()))
    client = SpotifyClient(
        str(paths.tokens_db()),
        settings.spotify_user_id,
        # client_id and fernet_key read from env by SpotifyClient
        os.environ.get("SPOTIFY_CLIENT_ID", ""),
        os.environ.get("TOKEN_ENCRYPT_KEY", "").encode(),
    )
    # Defer to existing sync helper if present; otherwise the user can use scripts/sync_api.py.
    try:
        from spotify_core.db.pipeline import sync_recent_plays  # type: ignore
    except ImportError:
        console.print(
            "[yellow]Recent-plays sync not yet wired into the pipeline. "
            "Run `uv run python scripts/sync_api.py` for now.[/yellow]"
        )
        return
    inserted = sync_recent_plays(client, str(paths.history_db()))
    console.print(f"[green]Synced {inserted} recent plays.[/green]")


def run_step(console: Console, import_path: Path | None = None) -> None:
    """Either import from a fixed path (--import flag) or run the interactive choice."""
    if import_path is not None:
        from spotify_core.db.pipeline import import_json_to_db

        result = import_json_to_db(str(import_path), str(paths.history_db()))
        console.print(
            f"[green]Imported {result['inserted']} rows from {import_path}.[/green]"
        )
        return

    console.print(Panel.fit(_REQUEST_BANNER, title="Step 5 / 6: Load listening history"))

    choice = _prompt_choice(console)
    if choice == "skip":
        console.print("Skipping history load. Re-run `spotify-mcp setup` any time.")
        return
    if choice == "sync":
        _do_sync_recent(console)
        return

    # choice == "import" — try GUI first, fall back to cwd scan
    selected_dir = pick_dir_via_gui()
    if selected_dir is not None:
        files = scan_dir(selected_dir)
        if not files:
            console.print(
                f"[yellow]No Streaming_History_Audio_*.json files found in {selected_dir}.[/yellow]"
            )
            return
        _do_import(console, files)
        return

    # GUI unavailable or cancelled — offer cwd scan as fallback
    cwd_files = scan_dir(Path.cwd())
    if _confirm_use_cwd(console, cwd_files):
        _do_import(console, cwd_files)
```

Note: the `import os` inside `run_step` is required because `_do_sync_recent` references it; keep the function self-contained for testability. (If pyflakes complains about unused import in test paths, move it to module level.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_history_import.py -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/history_import.py tests/mcp/test_wizard_history_import.py
git commit -m "feat(mcp): wizard step — interactive history import via cwd scan"
```

---

## Task 10: Claude Desktop config writer

**Files:**
- Create: `apps/mcp/spotify_mcp/wizard/claude_desktop.py`
- Test: `tests/mcp/test_wizard_claude_desktop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_wizard_claude_desktop.py`:

```python
"""Tests for wizard.claude_desktop — locate, diff, and merge the config."""
import json
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import claude_desktop as cd


def test_build_entry_uses_resolved_path():
    entry = cd.build_entry(script_path="/home/u/.local/bin/spotify-mcp")
    assert entry["command"] == "/home/u/.local/bin/spotify-mcp"
    assert entry["args"] == ["serve"]


def test_compute_merge_into_empty(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    merged = cd.compute_merged(cfg, entry={"command": "X", "args": []})
    assert merged == {"mcpServers": {"spotify-mcp": {"command": "X", "args": []}}}


def test_compute_merge_preserves_other_keys(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"other": {"command": "Y", "args": []}},
        "theme": "dark",
    }))
    merged = cd.compute_merged(cfg, entry={"command": "X", "args": []})
    assert merged["mcpServers"]["other"] == {"command": "Y", "args": []}
    assert merged["mcpServers"]["spotify-mcp"] == {"command": "X", "args": []}
    assert merged["theme"] == "dark"


def test_write_with_backup_creates_timestamped_backup(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"existing": True}))
    cd.write_with_backup(cfg, {"merged": True})
    assert cfg.read_text() == json.dumps({"merged": True}, indent=2)
    # exactly one backup file
    backups = list(tmp_path.glob("claude_desktop_config.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"existing": True}


def test_diff_text_shows_added_entry(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    diff = cd.diff_text(cfg, {"mcpServers": {"spotify-mcp": {"command": "X", "args": []}}})
    assert "spotify-mcp" in diff
    assert "+" in diff  # diff markers
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_wizard_claude_desktop.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `claude_desktop.py`**

Create `apps/mcp/spotify_mcp/wizard/claude_desktop.py`:

```python
"""Wizard step: locate Claude Desktop config, show a diff, merge with backup."""
import difflib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.syntax import Syntax


def default_config_path() -> Path:
    """Per-OS path Claude Desktop reads its MCP config from."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Claude" / "claude_desktop_config.json"
    # Linux + others
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def resolve_script_path() -> Optional[str]:
    """Find the absolute path to the installed `spotify-mcp` script.

    Claude Desktop's spawn does not always inherit user PATH, so we must write
    the resolved absolute path into the config.
    """
    return shutil.which("spotify-mcp")


def build_entry(script_path: str) -> dict:
    return {"command": script_path, "args": ["serve"]}


def compute_merged(config_path: Path, entry: dict) -> dict:
    """Return the merged config dict (does not write)."""
    if config_path.exists():
        try:
            current = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            current = {}
    else:
        current = {}

    servers = current.get("mcpServers", {})
    servers["spotify-mcp"] = entry
    current["mcpServers"] = servers
    return current


def diff_text(config_path: Path, merged: dict) -> str:
    """Unified diff between current file and proposed merged content."""
    before = config_path.read_text() if config_path.exists() else ""
    after = json.dumps(merged, indent=2)
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=str(config_path),
            tofile=str(config_path) + " (proposed)",
            lineterm="",
        )
    )


def write_with_backup(config_path: Path, merged: dict) -> Optional[Path]:
    """Write merged content; back up any existing file. Returns backup path or None."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    if config_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_name(f"{config_path.name}.bak.{ts}")
        shutil.copy2(config_path, backup)
    config_path.write_text(json.dumps(merged, indent=2))
    return backup


def run_step(console: Console, install: bool) -> None:
    """The full Claude Desktop config step.

    With install=False, prints the snippet for manual copy. With install=True,
    locates the config, shows a diff, asks for confirmation, then writes with backup.
    """
    script_path = resolve_script_path()
    if script_path is None:
        script_path = console.input(
            "Could not auto-detect the `spotify-mcp` script path. "
            "Please paste the absolute path: "
        ).strip()

    entry = build_entry(script_path)
    snippet = json.dumps({"mcpServers": {"spotify-mcp": entry}}, indent=2)

    if not install:
        console.print("\n[bold]Add this to your Claude Desktop config:[/bold]\n")
        console.print(Syntax(snippet, "json", theme="ansi_dark"))
        console.print(f"\nConfig location: {default_config_path()}")
        return

    cfg_path = default_config_path()
    if not cfg_path.exists():
        console.print(
            f"[yellow]Claude Desktop config not found at {cfg_path}.\n"
            "Open Claude Desktop → Help → Troubleshooting → Enable Developer Mode, then re-run.\n"
            "If the file still doesn't appear, open it via "
            "Developer Mode → Open App Config File... and paste the snippet below manually:[/yellow]\n"
        )
        console.print(Syntax(snippet, "json", theme="ansi_dark"))
        return

    merged = compute_merged(cfg_path, entry)
    console.print("\n[bold]Proposed change to Claude Desktop config:[/bold]")
    console.print(diff_text(cfg_path, merged) or "(no diff — entry already present)")
    confirm = console.input("\nApply this change? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("Skipped. The snippet above is yours to paste manually.")
        return

    backup = write_with_backup(cfg_path, merged)
    console.print(f"[green]Updated {cfg_path}.[/green]")
    if backup:
        console.print(f"Backup: {backup}")
```

Note: add `import os` at the top of the file (it's used in `default_config_path()` on Windows).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/test_wizard_claude_desktop.py -v`
Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/claude_desktop.py tests/mcp/test_wizard_claude_desktop.py
git commit -m "feat(mcp): wizard step — Claude Desktop config diff + merge"
```

---

## Task 11: Wire all wizard steps in resumable order

**Files:**
- Modify: `apps/mcp/spotify_mcp/wizard/__init__.py`
- Test: `tests/mcp/test_cli_setup.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/mcp/test_cli_setup.py`:

```python
def test_setup_resumes_when_already_configured(tmp_path, monkeypatch):
    """If state checks pass, the wizard should not re-run completed steps."""
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))

    # Stub every check to True
    import spotify_mcp.wizard.state as state
    monkeypatch.setattr(state, "has_client_id", lambda: True)
    monkeypatch.setattr(state, "has_fernet_key", lambda: True)
    monkeypatch.setattr(state, "dbs_initialized", lambda: True)
    monkeypatch.setattr(state, "tokens_valid", lambda: True)
    monkeypatch.setattr(state, "history_has_data", lambda: True)

    # Stub the heavy steps so the test doesn't open browsers etc.
    import spotify_mcp.wizard.spotify_app as sa
    import spotify_mcp.wizard.credentials as cr
    import spotify_mcp.wizard.oauth_step as os_
    import spotify_mcp.wizard.history_import as hi
    import spotify_mcp.wizard.claude_desktop as cdk

    called: list[str] = []
    monkeypatch.setattr(sa, "run_step", lambda **k: called.append("spotify_app"))
    monkeypatch.setattr(cr, "prompt_client_id", lambda console: called.append("client_id") or "x")
    monkeypatch.setattr(cr, "ensure_fernet_key", lambda console: called.append("fernet") or "x")
    monkeypatch.setattr(os_, "run_oauth", lambda **k: called.append("oauth"))
    monkeypatch.setattr(hi, "run_step", lambda **k: called.append("history"))
    monkeypatch.setattr(cdk, "run_step", lambda **k: called.append("claude_desktop"))

    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    # All checks pass → no step gets called
    assert called == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_cli_setup.py::test_setup_resumes_when_already_configured -v`
Expected: FAIL — wizard still raises `NotImplementedError`.

- [ ] **Step 3: Implement `wizard/__init__.py`**

Replace `apps/mcp/spotify_mcp/wizard/__init__.py`:

```python
"""Setup wizard orchestration — composes resumable steps."""
from pathlib import Path
from typing import Optional

from rich.console import Console

from spotify_core import paths

from . import (
    claude_desktop,
    credentials,
    history_import,
    oauth_step,
    spotify_app,
    state,
)


def run_wizard(
    install_claude_desktop: bool,
    import_path: Optional[Path],
    console: Console,
) -> None:
    """Run the setup wizard, skipping any already-completed step.

    With ``import_path``, skip the wizard entirely and just import that file/dir.
    """
    paths.ensure_dirs()

    if import_path is not None:
        history_import.run_step(console=console, import_path=import_path)
        return

    # Step 2 — Spotify app registration (always shows; cheap, idempotent)
    if not state.has_client_id():
        spotify_app.run_step(console=console)
        # Step 3 — Client ID
        credentials.prompt_client_id(console)

    # Step 4 — Fernet key
    if not state.has_fernet_key():
        credentials.ensure_fernet_key(console=console)

    # Step 5 — DBs
    if not state.dbs_initialized():
        from spotify_core.db.migrations import init_history_db, init_ltm_db, init_tokens_db
        init_history_db(paths.history_db())
        init_tokens_db(paths.tokens_db())
        init_ltm_db(paths.ltm_db())
        console.print("[green]Databases initialized.[/green]")

    # Step 6 — OAuth
    if not state.tokens_valid():
        oauth_step.run_oauth(console=console, force=False)

    # Step 7 — History import (only if no data yet — otherwise nothing to do)
    if not state.history_has_data():
        history_import.run_step(console=console, import_path=None)

    # Step 8 — Claude Desktop config (always offered; user picks via --install-claude-desktop)
    claude_desktop.run_step(console=console, install=install_claude_desktop)

    console.print("\n[bold green]Setup complete.[/bold green]")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/ -v`
Expected: all pass.

- [ ] **Step 5: Smoke-test the CLI with `--help` and `doctor`**

Run: `uv run spotify-mcp doctor`
Expected: prints a JSON report (likely with several `actions_needed` entries on a fresh checkout) and exits.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp/spotify_mcp/wizard/__init__.py tests/mcp/test_cli_setup.py
git commit -m "feat(mcp): wire wizard steps into a resumable run_wizard"
```

---

## Task 12: Update MCP server lifespan + remove legacy `setup` tool

**Files:**
- Modify: `apps/mcp/server.py`
- Modify: `apps/mcp/spotify_mcp/config.py`
- Test: `tests/mcp/test_server_lifespan.py`

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_server_lifespan.py`:

```python
"""Tests for the MCP server lifespan — fail-fast on missing config."""
import asyncio
import io
import sys

import pytest


def test_lifespan_writes_actionable_stderr_when_dbs_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)

    from server import lifespan, mcp  # type: ignore

    async def _run():
        async with lifespan(mcp):
            pass

    with pytest.raises(SystemExit):
        asyncio.run(_run())

    captured = capsys.readouterr()
    assert "spotify-mcp setup" in captured.err
```

(If `server.py` is not importable from the test path, add `apps/mcp` to `pythonpath` via `tests/conftest.py` or import via the installed entry-point.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_server_lifespan.py -v`
Expected: FAIL — current lifespan creates DBs silently and never exits.

- [ ] **Step 3: Update `server.py`**

In `apps/mcp/server.py`:

- Delete the `_ensure_dbs_initialized` function and its call in `lifespan`.
- Delete the `setup` MCP tool block (the function decorated with `@mcp.tool(name="setup", ...)` and its body, lines ~200–228).
- Replace the lifespan body with the fail-fast logic below.

```python
@asynccontextmanager
async def lifespan(server: FastMCP):
    from spotify_mcp.wizard.state import collect_report

    report = collect_report()
    blocking = [
        a for a in report["actions_needed"]
        if "Load history" not in a  # history-empty is not blocking
    ]
    if blocking:
        msg = "spotify-mcp not configured. Run: spotify-mcp setup"
        # stderr -> Claude Desktop's MCP error UI shows this
        print(msg, file=sys.stderr, flush=True)
        for a in blocking:
            print(f"  - {a}", file=sys.stderr, flush=True)
        logger.error("%s\n%s", msg, "\n".join(f"  - {a}" for a in blocking))
        raise SystemExit(1)

    logger.info("MCP server ready: all checks passed.")
    yield
```

Add `import sys` near the top of `server.py` if not already present.

- [ ] **Step 4: Update `spotify_mcp/config.py` to load env from new location**

Replace the top of `apps/mcp/spotify_mcp/config.py`:

```python
"""Shared MCP server config: paths, env, helpers used by every tool module."""
import logging
import os

from dotenv import load_dotenv

from spotify_core import paths

# Load env from the user's config dir first, then fall back to repo .env if it exists
# (covers the workspace dev case before SPOTIFY_MCP_CONFIG_DIR is set).
if paths.env_file().exists():
    load_dotenv(paths.env_file())
load_dotenv()  # safe no-op if cwd has no .env

from spotify_core.config import settings

logger = logging.getLogger(__name__)
```

Then update the path constants near the bottom of the file:

```python
DB_PATH: str = str(settings.history_db_path)
TOKENS_DB: str = str(settings.tokens_db_path)
LTM_DB: str = str(settings.ltm_db_path)
DEFAULT_USER_ID: str = settings.spotify_user_id
```

(Same as today — they already flow through settings, so no change needed here other than confirming they still resolve.)

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ -v`
Expected: pass.

- [ ] **Step 6: Manual smoke test — server fails fast on a clean home**

Run (in a temp working dir with `SPOTIFY_MCP_CONFIG_DIR` and `SPOTIFY_MCP_DATA_DIR` pointing to a fresh empty dir):
```
SPOTIFY_MCP_CONFIG_DIR=/tmp/sm-cfg SPOTIFY_MCP_DATA_DIR=/tmp/sm-data uv run python apps/mcp/server.py
```
Expected: exits non-zero, stderr says `spotify-mcp not configured. Run: spotify-mcp setup`.

- [ ] **Step 7: Commit**

```bash
git add apps/mcp/server.py apps/mcp/spotify_mcp/config.py tests/mcp/test_server_lifespan.py
git commit -m "refactor(mcp): fail-fast lifespan + remove in-Claude setup tool"
```

---

## Task 13: PyPI metadata + rename packages

**Files:**
- Modify: `packages/core/pyproject.toml`
- Modify: `packages/dataloader/pyproject.toml`
- Modify: `apps/mcp/pyproject.toml`
- Modify: root `pyproject.toml` (workspace declaration)

- [ ] **Step 1: Rename `spotify-core`**

Edit `packages/core/pyproject.toml`:

```toml
[project]
name = "spotify-analytics-core"
version = "0.1.0"
description = "Core analytics, agent, and Spotify client library for the Spotify AI Analytics project."
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "WC Chang" }]
requires-python = ">=3.13"
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Intended Audience :: Developers",
]
dependencies = [
    "langgraph>=1.0",
    "langchain-core>=1.0",
    "langchain-openai>=1.0",
    "langchain-google-genai>=4.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "cryptography>=42.0",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "langgraph-checkpoint-sqlite>=3.0.3",
    "platformdirs>=4.0",
]
```

- [ ] **Step 2: Rename `spotify-dataloader`**

Edit `packages/dataloader/pyproject.toml` similarly: `name = "spotify-analytics-dataloader"`, add description/license/classifiers/authors.

- [ ] **Step 3: Rename `spotify-mcp`**

Edit `apps/mcp/pyproject.toml`:

```toml
[project]
name = "spotify-analytics-mcp"
version = "0.1.0"
description = "MCP server (and CLI installer) for the Spotify AI Analytics project."
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "WC Chang" }]
requires-python = ">=3.13"
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Intended Audience :: Developers",
]
dependencies = [
    "fastmcp>=2.0",
    "spotify-analytics-core==0.1.0",
    "spotify-analytics-dataloader==0.1.0",
    "typer>=0.12",
    "rich>=13.7",
    "platformdirs>=4.0",
]

[project.scripts]
spotify-mcp = "spotify_mcp.cli:app"

[tool.uv.sources]
spotify-analytics-core = { workspace = true }
spotify-analytics-dataloader = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["spotify_mcp"]
```

- [ ] **Step 4: Update root `pyproject.toml` workspace member references**

Open the root `pyproject.toml` and update workspace member declarations and any cross-references from `spotify-core` / `spotify-dataloader` / `spotify-mcp` to the new names.

Run `uv sync` to confirm the workspace still resolves.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: pass.

- [ ] **Step 6: Build the wheels (dry run, do not publish)**

Run:
```bash
uv build packages/core
uv build packages/dataloader
uv build apps/mcp
```
Expected: each produces `dist/*.whl` and `dist/*.tar.gz` in its respective directory with the new package names.

- [ ] **Step 7: Commit**

```bash
git add packages/core/pyproject.toml packages/dataloader/pyproject.toml apps/mcp/pyproject.toml pyproject.toml
git commit -m "build: rename packages to spotify-analytics-* and add PyPI metadata"
```

---

## Task 14: End-to-end install verification

**Files:**
- None (manual verification)

- [ ] **Step 1: Install the freshly-built wheel into a throwaway env**

```bash
# Use a temp dir as a fresh home
TMP=$(mktemp -d)
HOME=$TMP uv tool install --from "$(ls apps/mcp/dist/spotify_analytics_mcp-*.whl | head -1)" \
    --with "$(ls packages/core/dist/spotify_analytics_core-*.whl | head -1)" \
    --with "$(ls packages/dataloader/dist/spotify_analytics_dataloader-*.whl | head -1)" \
    spotify-analytics-mcp
```

Expected: `spotify-mcp` script ends up in `$TMP/.local/bin`.

- [ ] **Step 2: Run `--help`**

```bash
HOME=$TMP $TMP/.local/bin/spotify-mcp --help
```
Expected: typer help screen prints `setup`, `doctor`, `reauth`.

- [ ] **Step 3: Run `doctor`**

```bash
HOME=$TMP $TMP/.local/bin/spotify-mcp doctor
```
Expected: JSON report listing `actions_needed` (no client id, no fernet key, etc.). Exit code 1.

- [ ] **Step 4: Verify config dir is created on first wizard call**

Run `spotify-mcp setup` non-interactively up to the Spotify-app step (which is the first user-input gate). Inspect `$TMP/.config/spotify-mcp/` (Linux) — directory should exist after the run, even if the user aborts at the prompt.

- [ ] **Step 5: Cleanup + final commit (if any tweaks needed)**

If any commands above failed, fix the underlying issue, re-run from Step 1 of this task, and commit the fix with a clear message.

```bash
rm -rf "$TMP"
```

---

## Self-Review Notes

Before merging, scan the spec sections against the tasks:

- §1 PyPI layout → Task 13
- §2 End-user install → Task 13 (entry point), Task 14 (verify)
- §3 CLI subcommands → Tasks 4, 11, 14 (cli.py wiring + smoke test)
- §3 wizard step 1 (resolve dirs) → Tasks 1, 11 (`paths.ensure_dirs()` in `run_wizard`)
- §3 wizard step 2 (port probe + checklist) → Task 6
- §3 wizard step 3 (client id) → Task 7
- §3 wizard step 4 (fernet key) → Task 7
- §3 wizard step 5 (DB init) → Task 11 (inlined in `run_wizard`)
- §3 wizard step 6 (OAuth) → Task 8
- §3 wizard step 7 (history import) → Task 9
- §3 wizard step 8 (Claude Desktop config) → Task 10
- §3 resumability → Task 5 + Task 11
- §4 server lifespan changes → Task 12
- §5 path resolution → Tasks 1, 2
- §6 testing → covered per-task
