# PyPI Packaging & CLI-Driven Setup — Design

**Date:** 2026-05-05
**Status:** Approved (awaiting implementation plan)
**Scope:** Phase 1 (MCP server)

## Problem

The current setup is hostile to non-developers. Today they must:

1. Clone the repo
2. Install `uv`
3. Run `uv sync`
4. Manually create a Spotify developer app
5. Hand-edit `.env` with `SPOTIFY_CLIENT_ID` and a Fernet `TOKEN_ENCRYPT_KEY` (generated via a Python one-liner)
6. Run `scripts/setup.py` for OAuth + DB init
7. Hand-edit `claude_desktop_config.json` with absolute paths to the repo

We want the install to be: `uv tool install spotify-analytics-mcp && spotify-mcp setup`.

## Constraints

- **Spotify API forbids a shared Client ID for this use case.** Free-tier apps run in Development Mode (≤25 allowlisted users). Extended Quota Mode requires Spotify review and personal-analytics tools are routinely rejected. Every end user must register their own app.
- **OAuth needs a registered redirect URI** before any login attempt, so the Client-ID step must precede the OAuth step.
- **Workspace boundary should be preserved.** Phase 2's web app reuses `spotify_core` and `spotify_dataloader` directly; collapsing them into MCP-internal modules now creates a refactor we'd undo in Phase 2.

## Decision Summary

- Publish three PyPI packages from the existing workspace; users install only one.
- A new `spotify-mcp` CLI (typer-based) handles all one-time setup.
- The MCP server's lifespan is reduced to `setup_check` only — no implicit DB creation, no in-Claude setup tool.
- Config and data paths move from the repo's `data/` into platform-standard user dirs when running installed.

## 1. PyPI Package Layout

| PyPI name | Source | Notes |
|---|---|---|
| `spotify-analytics-core` | `packages/core/` | Public; reused by Phase 2 web app |
| `spotify-analytics-dataloader` | `packages/dataloader/` | Public; pure-function ingestion |
| `spotify-analytics-mcp` | `apps/mcp/` | The only package end users install |

**Versioning:** all three released in lockstep with matching versions. `spotify-analytics-mcp` pins `spotify-analytics-core==<same>` and `spotify-analytics-dataloader==<same>` at publish time.

**Local development:** `[tool.uv.sources]` blocks keep workspace sources active in the checkout. `uv` resolves to workspace members locally and falls back to PyPI versions when installed standalone.

**Distribution name vs import name:** PyPI names use `spotify-analytics-*`; Python import names stay as today (`spotify_core`, `spotify_dataloader`, `spotify_mcp`).

## 2. End-User Install

**Primary command:**

```bash
uv tool install spotify-analytics-mcp &&
spotify-mcp setup
```

**Fallback (no uv):** `pipx install spotify-analytics-mcp`.

`uv tool install` creates an isolated environment and places the `spotify-mcp` entry-point script on the user's PATH (`~/.local/bin` on Unix, `%USERPROFILE%\.local\bin` on Windows). `uvx` (ephemeral run) is intentionally **not** recommended here because Claude Desktop spawns the MCP server as a long-running stdio process and needs a stable path.

## 3. CLI

**Module:** `apps/mcp/spotify_mcp/cli.py`
**Entry point:** `[project.scripts] spotify-mcp = "spotify_mcp.cli:app"`
**Library:** `typer` + `rich` for prompts and styled output.

### Subcommands

| Command | Purpose |
|---|---|
| `spotify-mcp setup` | First-run wizard. Default if no subcommand. |
| `spotify-mcp setup -setup-claude-desktop` | Wizard + write Claude Desktop config |
| `spotify-mcp setup --import <path>` | Skip wizard; import a Spotify JSON export into the existing install |
| `spotify-mcp doctor` | Run `setup_check` and print report |
| `spotify-mcp reauth` | Re-run OAuth flow only (recovery) |

### Wizard Steps (`spotify-mcp setup`)

1. **Resolve config + data dirs.** Use `platformdirs.user_config_dir("spotify-mcp")` and `user_data_dir("spotify-mcp")`. Create both if missing.
2. **Spotify app registration.** Open `https://developer.spotify.com/dashboard` in the default browser, then print a numbered checklist the user should complete in the dashboard:
   1. Click "Create app"
   2. Enter any name and description
   3. **Redirect URI:** paste `http://127.0.0.1:8888/callback` exactly, then click "Add"
   4. API/SDK: select "Web API"
   5. Accept ToS, click "Save"
   6. Open the app's Settings page and copy the Client ID

   Before showing the checklist, **probe TCP port 8888** for availability. If it's already bound, abort with a clear error explaining the port must be free for OAuth and listing common causes (Docker, another running instance). The redirect URI is pinned because it's registered in the Spotify dashboard upfront — dynamic ports are not viable.
3. **Prompt for Client ID.** Persist to `<config_dir>/.env`. Validation is intentionally lax: require non-empty, strip whitespace, warn (don't reject) if it doesn't look like 32 hex chars — Spotify's exact format isn't publicly specified and over-strict validation creates false rejections.
4. **Generate Fernet key.** If `TOKEN_ENCRYPT_KEY` is already present in `<config_dir>/.env`, skip this step entirely (regenerating would orphan all stored tokens). Otherwise `Fernet.generate_key()` → persist. After writing the `.env` file, set permissions to `0600` on Unix; on Windows, rely on the user-profile ACL inherited from `<config_dir>` (no chmod equivalent for the secret-only case worth adding here). Print a one-line warning: "Do not delete `<config_dir>/.env` — losing the key makes stored tokens unrecoverable."
5. **Initialize SQLite DBs.** Call `init_history_db`, `init_tokens_db`, `init_ltm_db` against paths under `<data_dir>/`.
6. **OAuth browser flow.** Reuse the existing `spotify_core.spotify_client` PKCE flow. CLI owns the localhost listener on port 8888; success encrypts and stores tokens. (Exact integration point — how the CLI injects its listener into the existing PKCE flow — is deferred to the implementation plan.)
7. **History import (optional but recommended).** Show this message:

   > **We recommend requesting your full Spotify listening history from Spotify Privacy.** It contains years of plays vs. only the last 50 from the live API, and it's what makes the analytics meaningful. Request it at https://www.spotify.com/account/privacy/ — it takes ~5 days to arrive by email. Once you have it, re-run the wizard or `spotify-mcp setup --import <path>`.

   Then offer (no path typing in the wizard):
   - `[1]` **Import JSON export now.** Open a native folder-picker dialog (tkinter `filedialog.askdirectory`); after the user picks a directory, scan it (non-recursive) for `Streaming_History_Audio_*.json` and confirm the file list before importing. If the user cancels the dialog, the import is skipped. Tk is attempted lazily inside a `try/except` — if `tkinter` is missing or `Tk()` raises (headless env, no X server, broken `_tkinter`), the wizard falls back to scanning the current working directory for `Streaming_History_Audio_*.json` and printing instructions to drop files there. The `--import <path>` flag is retained as a power-user/scripting affordance and is the recommended path for headless installs.
      - *comment:* Use tkinter as alternatvies to activate GUI for user to select JSON files directory. If user not select, skip import.
      ```python            
      import tkinter as tk
      from tkinter import filedialog

      def pick_directory():
         root = tk.Tk()
         root.withdraw()   # 不顯示主視窗

         folder_path = filedialog.askdirectory(title="選擇資料夾")

         root.destroy()
         return folder_path

      def find_json_files(folder_path):
         p = Path(folder_path)
         # only find one layer of json files, not recursive
         return list(p.glob("*.json"))


      def pick_json_dir():
         print("請選擇一個資料夾，程式將會尋找該資料夾內的 JSON 檔案")
         folder = pick_directory()

         if not folder:
            print("沒有選擇資料夾")
         else:
            json_files = find_json_files(folder)

            if not json_files:
                  print("該資料夾內沒有符合條件的 JSON 檔")
            else:
                  print("找到以下 JSON 檔：")
                  for f in json_files:
                     print(f)
      ```
   - `[2]` Sync recent 50 plays from the API (instant, partial)
   - `[3]` Skip — I'll do this later

   The import operation runs inside a single SQLite transaction; any per-record failure rolls back the whole import and reports which file/record failed.

8. **Claude Desktop config.** Print the JSON snippet with absolute paths. If `--setup-claude-desktop`:
   - Resolve the script path via `shutil.which("spotify-mcp")` (Claude Desktop's spawn does not always inherit user PATH, so the config must use the absolute path). If `which` returns nothing, prompt the user to paste the absolute path.
   - Locate `claude_desktop_config.json` at the OS-specific path. If it does not exist (e.g., user installed the `.msi` build, or has not enabled Developer Mode), print the fallback: *"Open Claude Desktop → Help → Troubleshooting → Enable Developer Mode, then re-run this command."*
   - Back up the existing file to `claude_desktop_config.json.bak.<timestamp>`.
   - Compute the merge of the new `mcpServers.spotify-mcp` entry, **show a diff to the user**, and require confirmation before writing. Existing keys other than `spotify-mcp` are preserved; an existing `spotify-mcp` entry is overwritten after explicit confirmation.

### Resumability

Each step checks current state before acting and skips when already satisfied. State checks:

- **Client ID present?** Non-empty `SPOTIFY_CLIENT_ID` in `<config_dir>/.env`.
- **Fernet key present?** Non-empty `TOKEN_ENCRYPT_KEY` in `<config_dir>/.env`.
- **DBs initialized?** All three SQLite files exist with their expected schema (verified by trying a no-op `SELECT` against a known table).
- **Tokens valid?** Row exists in `tokens.db` for the default user, decrypts cleanly with the current Fernet key, and contains a non-empty `refresh_token`. Expiry of the *access* token is not checked — refresh handles that at runtime. Live Spotify reachability is not pinged (slow, requires network).

Re-running `spotify-mcp setup` after a partial run resumes at the first failing check.

## 4. MCP Server Lifespan Changes

**`apps/mcp/server.py`:**

- **Remove** `_ensure_dbs_initialized()`. If DBs are missing, lifespan writes a single-line actionable message to **stderr** (which Claude Desktop surfaces in its MCP error UI) — e.g. `spotify-mcp not configured. Run: spotify-mcp setup` — in addition to the structured log line, then exits non-zero. No silent DB creation.
- **Remove** the `setup` MCP tool (`server.py` lines ~200–228). Recovery flows live in the CLI.
- **Keep** the `setup_check` MCP tool unchanged (it's still useful as in-Claude diagnostics).
- **Replace** `load_dotenv()` from repo root with a helper in `spotify_core.config` that loads `<config_dir>/.env` first, then falls back to repo-local `.env` only when running from a checkout.

## 5. Path & Config Refactor

`spotify_core.config.settings` currently hardcodes `data/` relative to repo root. New resolution priority for both the data dir and the `.env` location:

1. **Explicit env override** — `SPOTIFY_MCP_DATA_DIR` / `SPOTIFY_MCP_CONFIG_DIR`
2. **Default** — `platformdirs.user_data_dir("spotify-mcp")` / `user_config_dir("spotify-mcp")`

The previous "auto-detect checkout via parent-walking for `pyproject.toml`" idea is dropped — it's fragile (multiple `pyproject.toml` files exist in a workspace, behavior depends on cwd vs. import location). Instead, contributors working from a checkout opt in explicitly by setting `SPOTIFY_MCP_DATA_DIR=./data` and `SPOTIFY_MCP_CONFIG_DIR=.` (or any pair they prefer) in their shell profile or repo `.envrc`. This is a one-time setup with no surprises and no implicit precedence between `<repo>/.env` and `<config_dir>/.env`.

**New dependency:** `platformdirs` added to `spotify-analytics-core`.

## 6. Testing

| Test | Scope |
|---|---|
| Path resolution unit tests | All three branches of priority logic, with mocked `platformdirs` and env-var fixtures |
| CLI wizard tests | `typer.testing.CliRunner` with mocked browser-open, mocked OAuth callback, mocked filesystem; assert each step writes expected artifacts and the wizard resumes correctly when re-run mid-flow |
| `spotify-mcp doctor` integration | Run against a freshly-`setup`'d temp dir; assert "ready" |
| `--setup-claude-desktop` | Write into a temp config file (existing + missing cases); assert backup created and JSON merged correctly |
| MCP server tests | Update fixtures to use temp data dirs; remove tests for the deleted `setup` tool |

## 7. Out of Scope

- **Auto-creating the Spotify app.** Spotify has no API for app registration; this remains manual.
- **Phase 2 web app packaging.** This spec covers MCP only; web app gets its own packaging pass later.
- **Multi-user support on a single install.** Current single-user assumption (`DEFAULT_USER_ID` from settings) is preserved.
- **Auto-update notifications.** Out of scope.

## 8. Migration Notes for Existing Developers

Contributors working from a checkout must perform a **one-time opt-in** to keep using the repo's `data/` and `.env`:

```bash
# in repo root, add to your shell profile or a .envrc
export SPOTIFY_MCP_DATA_DIR="$PWD/data"
export SPOTIFY_MCP_CONFIG_DIR="$PWD"
```

Without this, the server reads from `platformdirs` paths and will appear "unconfigured" until `spotify-mcp setup` is run (or the env vars are set). This trade-off is accepted in exchange for dropping the fragile auto-detection. The other visible change: `apps/mcp/server.py` no longer creates DBs on demand — running the server before setup now fails fast with a stderr message.
