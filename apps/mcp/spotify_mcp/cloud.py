"""Cloudflare deploy, and the D1 -> local cache pull.

Two things live here and they are going in opposite directions:

- `deploy()` needs `node`/`npx` for wrangler, which is exactly why it cannot be
  what the desktop app calls: an external user standing up their own Cloudflare
  stack will not have Node. It is being replaced by direct Cloudflare REST calls
  from Rust. This remains the source-checkout path.
- `pull()` refreshes the local SQLite cache that MCP and report generation read.
  It stays.

`seed()` used to be the third: it pushed this machine's tokens.db and local
history *up* to D1. Neither exists any more — the app authorizes straight into D1
and posts the data export straight to the Worker — so there is nothing to push.

Nothing here prints a token or a track name: the repo is public and this output
is streamed into the Setup page log pane.

Note: wrangler auto-loads a `.env` from its own cwd, which here is worker/. A
`worker/.env` would therefore feed variables into a deploy without appearing
anywhere below. Latent, not live — and it disappears with wrangler.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from spotify_core import config_file

# Pinned major: wrangler 5 would be an unreviewed change to every command below.
WRANGLER = ["npx", "--yes", "wrangler@4"]
DEFAULT_NAME = "spotify-analytics"
WORKERS_DEV_RE = re.compile(r"https://[^\s]+\.workers\.dev")

# NOTE for the Rust/REST rewrite: a freshly-set Worker secret takes a few seconds
# to reach every edge node, so the first authenticated call after a deploy can
# 401. That is real propagation delay, not a flaky-test band-aid — whatever
# replaces this needs the same retry, and the knob for it.
SECRET_PROPAGATION_ATTEMPTS = 5
SECRET_PROPAGATION_BACKOFF_S = 5


def worker_dir() -> Path:
    """The repo's worker/ directory. ponytail: swaps to a bundled path when packaged."""
    return (Path(__file__).resolve().parents[3] / "worker").resolve()


def _resolve(program: str) -> str:
    """Absolute path to *program*.

    On Windows npx is `npx.cmd`, and CreateProcess only looks for `.exe` — the
    bare name raises WinError 2. shutil.which applies PATHEXT, which is the fix
    that does not involve shell=True.
    """
    found = shutil.which(program)
    if not found:
        raise RuntimeError(
            f"`{program}` not found. Deploying needs Node.js (>= 18) on PATH — "
            "install it from nodejs.org, then reopen the app so it picks up the new PATH."
        )
    return found


def _run(args: list[str], *, cwd: Path, env: Optional[dict] = None,
         stdin_text: Optional[str] = None, check: bool = True) -> str:
    """Run a command, streaming nothing, returning stdout. Errors carry stderr."""
    args = [_resolve(args[0]), *args[1:]]
    # `d1 migrations apply` prompts for confirmation and only skips it when it
    # decides the session is non-interactive. Since stdout is captured, a prompt
    # would be invisible while the process waits on an inherited terminal --
    # a silent hang. DEVNULL turns that into an immediate EOF, and CI is the
    # documented way to say "nobody is here to answer".
    stdin_args = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    full_env = {**os.environ, "CI": "1", **(env or {})}
    proc = subprocess.run(
        args, cwd=cwd, env=full_env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **stdin_args,
    )
    if check and proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-12:])
        raise RuntimeError(f"`{' '.join(args[:3])} …` failed:\n{tail}")
    return proc.stdout or ""


def _wrangler(args: list[str], *, api_token: str = "", stdin_text: Optional[str] = None,
              check: bool = True) -> str:
    # CLOUDFLARE_API_TOKEN makes wrangler skip `login` entirely. Required for the
    # GUI path: `wrangler login` blocks on a browser round-trip and would hang a
    # spawned, non-tty process forever.
    env = {"CLOUDFLARE_API_TOKEN": api_token} if api_token else None
    return _run(WRANGLER + args, cwd=worker_dir(), env=env,
                stdin_text=stdin_text, check=check)


def _render_config(name: str, database_id: str) -> Path:
    """Write a throwaway wrangler config for this deploy.

    The repo's worker/wrangler.toml is deliberately never written by tooling: it
    is shared state, so patching it in place meant a `--name` test deploy left
    behind a database_id that the next prod deploy would happily use.

    It has to live *in* worker/ despite being temporary: `main = "src/index.ts"`
    and `migrations_dir = "migrations"` resolve relative to the config file, so
    moving this to a tempdir looks tidier and silently breaks the deploy.
    """
    template = (worker_dir() / "wrangler.toml.example").read_text(encoding="utf-8")
    text = re.sub(r'^name = ".*"$', f'name = "{name}-worker"', template, count=1, flags=re.M)
    text = re.sub(r'^database_name = ".*"$', f'database_name = "{name}"', text, count=1, flags=re.M)
    text = re.sub(r'^database_id = ".*"$', f'database_id = "{database_id}"', text, count=1, flags=re.M)
    if database_id not in text:
        raise RuntimeError("wrangler.toml.example no longer has a database_id line to fill in")

    fd, tmp = tempfile.mkstemp(prefix="wrangler-", suffix=".toml", dir=worker_dir())
    os.close(fd)
    path = Path(tmp)
    path.write_text(text, encoding="utf-8")
    return path


def _database_id(name: str, api_token: str) -> str:
    # create is idempotent in effect: an existing DB just errors and we look the
    # id up either way.
    _wrangler(["d1", "create", name], api_token=api_token, check=False)
    raw = _wrangler(["d1", "list", "--json"], api_token=api_token)
    # `npx` can prepend install chatter, so find the JSON rather than parsing all.
    start = raw.find("[")
    databases = json.loads(raw[start:]) if start >= 0 else []
    for db in databases:
        if db.get("name") == name:
            return db["uuid"]
    raise RuntimeError(f"D1 database {name!r} not found after create — check the API token's scopes")


def _tolerant_console() -> None:
    """Never let an un-encodable character kill a deploy.

    wrangler's output contains emoji, and a Windows console is whatever the
    system locale says (cp950 here) -- printing that raises UnicodeEncodeError
    *after* the Worker is already live. The Tauri spawn sets PYTHONUTF8=1 and so
    never saw it; a terminal run did. Replacing the odd character beats both
    crashing and forcing an encoding the console may not render.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass  # already-wrapped or non-reconfigurable stream: nothing to do


def deploy(name: str = DEFAULT_NAME, api_token: str = "", rotate: bool = False) -> int:
    """Create D1, migrate, deploy the Worker (cron goes live), set secrets."""
    _tolerant_console()
    target = config_file.path()
    client_id = config_file.read_key("SPOTIFY_CLIENT_ID") or ""
    fernet_key = config_file.read_key("TOKEN_ENCRYPT_KEY") or ""
    # The app's Setup page owns asking for these. If they are missing the user is
    # not ready for this step, and prompting here would be a second place to ask.
    if not client_id or not fernet_key:
        print("Finish Setup step 1 (Spotify Client ID) first — "
              f"{target} has no SPOTIFY_CLIENT_ID/TOKEN_ENCRYPT_KEY.", file=sys.stderr)
        return 1

    # Reuse the existing token. Minting a new one on every deploy (as the old
    # shell script did) silently 401s every other machine pointing at this
    # Worker; rotation has to be something you ask for.
    worker_token = config_file.read_key("WORKER_AUTH_TOKEN") or ""
    if rotate or not worker_token:
        worker_token = secrets.token_hex(32)
        print("Generated a new Worker auth token." if not rotate else "Rotating the Worker auth token.")

    print(f"==> [1/5] D1 database: {name}")
    database_id = _database_id(name, api_token)

    print("==> [2/5] Applying migrations")
    config = _render_config(name, database_id)
    try:
        cfg = ["-c", str(config)]
        _wrangler(["d1", "migrations", "apply", name, "--remote"] + cfg, api_token=api_token)

        print("==> [3/5] Deploying the Worker (the hourly cron goes live here)")
        out = _wrangler(["deploy"] + cfg, api_token=api_token)
        print(out)
        match = WORKERS_DEV_RE.search(out)
        worker_url = match.group(0) if match else ""

        print("==> [4/5] Worker secrets (never printed)")
        for key, value in (("AUTH_TOKEN", worker_token),
                           ("SPOTIFY_CLIENT_ID", client_id),
                           ("TOKEN_ENCRYPT_KEY", fernet_key)):
            _wrangler(["secret", "put", key] + cfg, api_token=api_token, stdin_text=value)
    finally:
        config.unlink(missing_ok=True)

    if worker_url:
        config_file.upsert("WORKER_URL", worker_url)
    config_file.upsert("WORKER_AUTH_TOKEN", worker_token)
    print(f"Wrote WORKER_URL/WORKER_AUTH_TOKEN to {target}")

    if not worker_url:
        print("! Could not parse the Worker URL from the deploy output — "
              "set WORKER_URL manually.", file=sys.stderr)
        return 1

    # Seeding used to be step 5: it pushed this machine's tokens.db and local
    # history up to D1. Neither exists to push any more — the app authorizes
    # straight into D1 and imports the data export straight into D1 — so there is
    # nothing to seed, only to pull back down.
    print(f"Done: D1 {name!r}, Worker deployed — the hourly cron (:07) is live.")
    print("Authorize Spotify in the app next; its tokens go directly to D1.")
    return 0


def pull(worker_url: str = "", worker_token: str = "", quiet: bool = False) -> int:
    """Refresh the local SQLite cache from D1.

    The cache is what the MCP server and report generation read. Idempotent:
    INSERT OR IGNORE from MAX(played_at).

    This is the only direction left. `seed()` pushed this machine's tokens.db and
    local history *up* to D1, and neither exists any more: the app authorizes
    straight into D1 and posts the data export straight to the Worker.
    """
    if not quiet:
        _tolerant_console()
    from spotify_core.config import load
    from spotify_core.db.local_sync import run_local_sync
    from spotify_core.db.worker_client import WorkerClient

    url = worker_url or config_file.read_key("WORKER_URL") or ""
    token = worker_token or config_file.read_key("WORKER_AUTH_TOKEN") or ""
    if not url or not token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set — nothing to pull from.", file=sys.stderr)
        return 1

    try:
        with WorkerClient(url, token) as worker:
            result = run_local_sync(load().history_db_path, worker)
    except Exception as exc:
        print(f"pull failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not quiet:
        print(f"local sync result: {result}")
    return 0
