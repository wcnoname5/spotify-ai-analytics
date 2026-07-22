"""Cloudflare deploy + seed, driven from the CLI (and therefore from the GUI).

Replaces scripts/setup_cloud.sh. Two things made the shell version wrong once the
Tauri Setup page existed:

- It prompted for SPOTIFY_CLIENT_ID and generated TOKEN_ENCRYPT_KEY itself, and
  reimplemented .env read/write in bash. The wizard now guarantees both, and
  spotify_core.env_file owns the .env format -- a second implementation of it is
  exactly the twin-.env class of bug.
- The GUI cannot assume a bash on Windows, and must not talk to wrangler
  directly: wrangler needs node/npx, which a packaged user will not have.

So the GUI calls `spotify-mcp cloud deploy` and nothing else. When this grows a
Cloudflare REST implementation (no node, no wrangler), only `_wrangler` and the
functions below change -- the CLI and GUI surface stay as they are.

Nothing here prints a token or a track name: the repo is public and this output
is streamed into the Setup page log pane.

Note: wrangler auto-loads a `.env` from its own cwd, which here is worker/. A
`worker/.env` would therefore feed variables into a deploy without appearing
anywhere below. The repo root .env is not read, so this is latent, not live.
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
import time
from pathlib import Path
from typing import Optional

from spotify_core import env_file, paths

# Pinned major: wrangler 5 would be an unreviewed change to every command below.
WRANGLER = ["npx", "--yes", "wrangler@4"]
DEFAULT_NAME = "spotify-analytics"
WORKERS_DEV_RE = re.compile(r"https://[^\s]+\.workers\.dev")

# A freshly-set `wrangler secret put` takes a few seconds to reach every edge
# node, so the first seed attempt can 401. Real propagation delay, not a retry
# band-aid -- keep the knob.
SEED_ATTEMPTS = 5
SEED_BACKOFF_S = 5


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


def _seed_module():
    """Imported lazily: it pulls in spotify_core.config, which reads the .env."""
    from spotify_mcp import seed

    return seed


def deploy(name: str = DEFAULT_NAME, api_token: str = "", rotate: bool = False) -> int:
    """Create D1, migrate, deploy the Worker (cron goes live), set secrets, seed."""
    _tolerant_console()
    target = paths.env_file()
    client_id = env_file.read_key(target, "SPOTIFY_CLIENT_ID") or ""
    fernet_key = env_file.read_key(target, "TOKEN_ENCRYPT_KEY") or ""
    # The wizard owns asking for these. If they are missing the user is not
    # ready for this step, and prompting here would be a second place to ask.
    if not client_id or not fernet_key:
        print("Finish Setup step 1 (Spotify Client ID) first — "
              f"{target} has no SPOTIFY_CLIENT_ID/TOKEN_ENCRYPT_KEY.", file=sys.stderr)
        return 1

    # Reuse the existing token. Minting a new one on every deploy (as the old
    # shell script did) silently 401s every other machine pointing at this
    # Worker; rotation has to be something you ask for.
    worker_token = env_file.read_key(target, "WORKER_AUTH_TOKEN") or ""
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
        env_file.upsert(target, "WORKER_URL", worker_url)
    env_file.upsert(target, "WORKER_AUTH_TOKEN", worker_token)
    print(f"Wrote WORKER_URL/WORKER_AUTH_TOKEN to {target}")

    if not worker_url:
        print("! Could not parse the Worker URL from the deploy output — "
              "set WORKER_URL manually.", file=sys.stderr)
        return 1

    # Deploying before authorizing Spotify is a legitimate order (the wizard
    # offers Cloud right after history), and there is nothing to push yet. The
    # retry loop below is for secret propagation only, so retrying a permanent
    # "no tokens here" five times would just be 25s of waiting.
    user_id = env_file.read_key(target, "SPOTIFY_USER_ID") or "default"
    if _seed_module().local_token_row(user_id) is None:
        print("==> [5/5] Nothing to seed yet — this machine has not authorized Spotify.")
        print("    Finish Setup step 2, then press Deploy again (or run `spotify-mcp cloud seed`).")
        print(f"Done: D1 {name!r}, Worker deployed — the hourly cron (:07) is live.")
        return 0

    print("==> [5/5] Seeding D1 (tokens + history) — skips whatever D1 already has")
    for attempt in range(1, SEED_ATTEMPTS + 1):
        if seed(worker_url, worker_token) == 0:
            break
        if attempt < SEED_ATTEMPTS:
            print(f"    (attempt {attempt}/{SEED_ATTEMPTS} failed — "
                  f"secret may still be propagating, retrying in {SEED_BACKOFF_S}s)")
            time.sleep(SEED_BACKOFF_S)
    else:
        print("! Seeding incomplete — the Worker is deployed; rerun "
              "`spotify-mcp cloud seed` once it settles.", file=sys.stderr)

    print(f"Done: D1 {name!r}, Worker deployed — the hourly cron (:07) is live.")
    return 0


def seed(worker_url: str = "", worker_token: str = "",
         force: bool = False, tokens_only: bool = False) -> int:
    """Push local tokens + history to D1. Rerun-safe; falls back to the .env values."""
    _tolerant_console()
    from spotify_core.db.worker_client import WorkerClient

    _seed = _seed_module()

    target = paths.env_file()
    url = worker_url or env_file.read_key(target, "WORKER_URL") or ""
    token = worker_token or env_file.read_key(target, "WORKER_AUTH_TOKEN") or ""
    if not url or not token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set", file=sys.stderr)
        return 1

    user_id = env_file.read_key(target, "SPOTIFY_USER_ID") or "default"
    # Every Worker call raises on a non-2xx, and the expected failure right
    # after a deploy is a 401 from a secret that has not reached every edge node
    # yet. deploy()'s retry loop can only act on that if it comes back as a
    # return code, so nothing may escape from here.
    try:
        with WorkerClient(url, token) as worker:
            tokens_ok = _seed.seed_tokens(worker, user_id, force=force)
            history_ok = True if tokens_only else _seed.seed_history(worker)
    except Exception as exc:
        print(f"seed failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0 if (tokens_ok and history_ok) else 1
