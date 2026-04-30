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
import sys
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from spotify_core.db.migrations import init_history_db, init_ltm_db, init_tokens_db
from spotify_core.db.queries import is_history_empty
from spotify_mcp import db_crud, memory_store, spotify_control
from spotify_mcp.config import (
    CLIENT_ID,
    DB_PATH,
    DEFAULT_USER_ID,
    FERNET_KEY,
    LTM_DB,
    PREMIUM_TOOLS,
    TOKENS_DB,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "DEBUG"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Startup env warnings (non-fatal)
# ------------------------------------------------------------------

if not CLIENT_ID:
    logger.warning(
        "SPOTIFY_CLIENT_ID is not set. Set it in .env or as an environment variable."
    )
if not FERNET_KEY:
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


def _get_account_product() -> Optional[str]:
    """Return the Spotify account product ('premium', 'free', …), or None if unknown."""
    if not FERNET_KEY or not CLIENT_ID:
        return None
    try:
        from spotify_core.spotify_client.token_store import load_tokens
        if load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY) is None:
            return None
        from spotify_core.spotify_client.client import SpotifyClient
        with SpotifyClient(TOKENS_DB, DEFAULT_USER_ID, CLIENT_ID, FERNET_KEY) as client:
            profile = client.get_current_user()
            return profile.get("product")
    except Exception as exc:
        logger.debug("Account product check skipped: %s", exc)
        return None


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

    # 3. Premium gating: drop playback tools if account is free / unknown-but-token-present.
    product = _get_account_product()
    if product is not None and product != "premium":
        for tool_name in PREMIUM_TOOLS:
            server.remove_tool(tool_name)
        logger.info("Spotify account type is %r — playback tools removed.", product)
    elif product == "premium":
        logger.info("Spotify Premium account confirmed — all tools enabled.")
    else:
        logger.debug("Account type unknown — all tools registered (fail-open).")

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
    checks: dict[str, bool] = {}
    actions: list[str] = []

    checks["spotify_client_id"] = bool(CLIENT_ID)
    if not CLIENT_ID:
        actions.append(
            "Set SPOTIFY_CLIENT_ID in .env\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file"
        )

    checks["token_encrypt_key"] = bool(FERNET_KEY)
    if not FERNET_KEY:
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
            checks["tokens_exist"] = load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY) is not None
        except Exception:
            pass

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


# Attach the rest of the tools.
db_crud.register(mcp)
spotify_control.register(mcp)
memory_store.register(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
