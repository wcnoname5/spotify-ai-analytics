"""Spotify AI Analytics MCP Server.

Exposes Spotify history analytics, playback control, and long-term memory
as MCP tools consumable by Claude Desktop / Claude Code.

Tool implementations live in spotify_mcp/{db_crud,spotify_control,memory_store}.py;
this file owns server boot, lifespan diagnostics, and the meta-tool `setup_check`.

Required environment variables:
    SPOTIFY_CLIENT_ID   — Spotify app client ID
    TOKEN_ENCRYPT_KEY   — Fernet key bytes (base64-encoded) for token encryption

Run:
    uv run python apps/mcp/server.py
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

from spotify_core.db.migrations import init_history_db, init_ltm_db, init_tokens_db
from spotify_core.db.queries import is_history_empty
from spotify_core.logging import setup_mcp_logging
from spotify_mcp import db_crud, memory_store, spotify_control
from spotify_mcp.prompts import register_prompts
from spotify_mcp.config import (
    DB_PATH,
    DEFAULT_USER_ID,
    LTM_DB,
    PREMIUM_TOOLS,
    TOKENS_DB,
    get_client_id,
    get_fernet_key,
)

load_dotenv()

_raw_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
_log_file = setup_mcp_logging(level=logging.getLevelNamesMapping().get(_raw_level, logging.DEBUG))
logger = logging.getLogger(__name__)
logger.info("Logging to %s", _log_file)


# ------------------------------------------------------------------
# Startup env warnings (non-fatal)
# ------------------------------------------------------------------

if not get_client_id():
    logger.warning(
        "SPOTIFY_CLIENT_ID is not set. Set it in .env or as an environment variable."
    )
if not get_fernet_key():
    logger.warning(
        "TOKEN_ENCRYPT_KEY is not set. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


# ------------------------------------------------------------------
# Lifespan helpers
# ------------------------------------------------------------------

def _ensure_dbs_initialized() -> Optional[str]:
    """Idempotently create history/tokens/ltm DBs. Returns an error string on failure."""
    try:
        init_history_db(DB_PATH)
        init_tokens_db(TOKENS_DB)
        init_ltm_db(LTM_DB)
        return None
    except Exception as exc:
        return (
            f"Failed to initialise local databases: {exc}\n"
            f"  history: {DB_PATH}\n"
            f"  tokens:  {TOKENS_DB}\n"
            f"  ltm:     {LTM_DB}\n"
            "Try running setup manually: uv run python scripts/setup.py"
        )

@asynccontextmanager
async def lifespan(server: FastMCP):
    # 1. Make sure every DB exists with its schema before any tool runs.
    db_err = _ensure_dbs_initialized()
    if db_err:
        logger.error(db_err)

    # 2. Diagnostics — log outstanding actions, don't block startup.
    result = setup_check()
    if not result["ready"]:
        logger.warning(
            "Server not fully configured. Outstanding actions:\n  - %s",
            "\n  - ".join(result["actions_needed"]),
        )
    else:
        logger.info("MCP server ready: all checks passed.")

    yield


# ------------------------------------------------------------------
# Server + tool registration
# ------------------------------------------------------------------

mcp = FastMCP("spotify_mcp", lifespan=lifespan)


@mcp.tool(
    name="setup_check",
    annotations={
        "title": "Check Server Setup",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
# TODO: move this function to spotify_core/setup.py and call it from here, so it can be reused in CLI tools without depending on the whole MCP server.
def setup_check() -> dict:
    """Diagnose the MCP server configuration. Call this first if something isn't working.

    Returns a structured report of what is configured and what actions are still needed,
    in the order they must be completed.

    Returns:
        {
            "ready": bool,
            "checks": dict[str, bool],
            "actions_needed": list[str],
            "message": str,
        }
    """
    logger.debug("[Tool] setup_check: running diagnostics on server configuration.")

    checks: dict[str, bool] = {}
    actions: list[str] = []

    client_id = get_client_id()
    fernet_key = get_fernet_key()

    checks["spotify_client_id"] = bool(client_id)
    if not client_id:
        actions.append(
            "Set SPOTIFY_CLIENT_ID in .env\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file"
        )

    checks["token_encrypt_key"] = bool(fernet_key)
    if not fernet_key:
        actions.append(
            "Run setup — auto-generates TOKEN_ENCRYPT_KEY, initializes DBs, and connects Spotify:\n"
            "  uv run python scripts/setup.py"
        )
    else:
        checks["ltm_db_exists"] = os.path.exists(LTM_DB)
        if not checks["ltm_db_exists"]:
            actions.append(
                "Long-term memory DB not found. Run scripts/setup.py to initialize it."
            )

        checks["history_db_exists"] = os.path.exists(DB_PATH)

        checks["tokens_exist"] = False
        try:
            from spotify_core.spotify_client.token_store import load_tokens
            checks["tokens_exist"] = load_tokens(TOKENS_DB, DEFAULT_USER_ID, fernet_key) is not None
        except Exception as exc:
            logger.error("[Tool] setup_check: Error occurred while checking tokens: %s", exc)

        if not checks["history_db_exists"] or not checks["tokens_exist"]:
            actions.append(
                "Initialize DB and connect Spotify (one command, opens browser):\n"
                "  uv run python scripts/setup.py"
            )
        else:
            checks["history_db_has_data"] = not is_history_empty(DB_PATH)
            if not checks["history_db_has_data"]:
                actions.append(
                    "Load listening history — choose one:\n"
                    "  A) Full export: place Streaming_History_Audio_*.json files in data/spotify_history/, then uv run python scripts/setup.py\n"
                    "     (download from https://www.spotify.com/account/privacy/)\n"
                    "  B) Recent plays: uv run python scripts/sync_api.py"
                )

    ready = len(actions) == 0
    return {
        "ready": ready,
        "checks": checks,
        "actions_needed": actions,
        "message": (
            "All set! MCP server is fully configured."
            if ready
            else f"{len(actions)} action(s) required to complete setup."
        ),
    }


@mcp.tool(
    name="setup",
    annotations={
        "title": "Run Setup",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def setup() -> dict[str, str | bool | dict]:
    """Run the full setup process: initialize DBs, connect Spotify, and optionally load history."""
    from spotify_core.setup import run_setup

    try:
        response = run_setup()

        return {
            "status": "success",
            "response": response,
            "message": "Setup completed successfully. Run `setup_check` to verify. You are able to use other tools."
            }
    except Exception as exc:
        logger.exception("Setup failed with an error.")
        return {
            "status": "failed",
            "response": {},
            "message": f"Setup failed: {exc}\nCheck server logs for details."
            }

# ------------------------------------------------------------------
# Prompts & tool registration
# ------------------------------------------------------------------

register_prompts(mcp)
db_crud.register(mcp)
spotify_control.register(mcp)
# TODO: memory schema design is still have flaws.
# Need to improve validation and error handling before enabling this.
# memory_store.register(mcp)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
