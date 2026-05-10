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

from dotenv import load_dotenv
from fastmcp import FastMCP

from spotify_core.logging import setup_mcp_logging
from spotify_mcp import db_crud, memory_store, spotify_control
from spotify_mcp.prompts import register_prompts
from spotify_mcp.config import (
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


@asynccontextmanager
async def lifespan(server: FastMCP):
    from spotify_mcp.wizard.state import collect_report

    report = collect_report()
    blocking = [
        action for action in report["actions_needed"]
        if "Load history" not in action
    ]
    if blocking:
        msg = "spotify-mcp not configured. Run: spotify-mcp setup"
        print(msg, file=sys.stderr, flush=True)
        for action in blocking:
            print(f"  - {action}", file=sys.stderr, flush=True)
        logger.error("%s\n%s", msg, "\n".join(f"  - {action}" for action in blocking))
        raise SystemExit(1)

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
    from spotify_mcp.wizard.state import collect_report

    return collect_report()

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
