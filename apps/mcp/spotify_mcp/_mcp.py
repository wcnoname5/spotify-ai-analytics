"""FastMCP application — mcp instance, tool registrations, and main().

This module owns the FastMCP app object so it can be imported by both the
development entry point (apps/mcp/server.py) and the `spotify-mcp serve`
CLI command without duplicating server logic.
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from spotify_mcp import db_crud, spotify_control
from spotify_mcp.config import get_client_id, get_fernet_key
from spotify_mcp.prompts import register_prompts

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP):
    from spotify_mcp.wizard.state import collect_report

    report = collect_report()
    blocking = [a for a in report["actions_needed"] if "Load history" not in a]
    if blocking:
        msg = "spotify-mcp not configured. Run: spotify-mcp setup"

        def _ascii_safe(s: str) -> str:
            # Replace Unicode dashes with ASCII hyphen so Windows consoles
            # (cp1252) don't produce un-decodable bytes in the stderr stream.
            return s.replace("—", "-").replace("–", "-")

        safe_msg = _ascii_safe(msg)
        print(safe_msg, file=sys.stderr, flush=True)
        safe_actions = [_ascii_safe(action) for action in blocking]
        for action in blocking:
            print(_ascii_safe(f"  - {action}"), file=sys.stderr, flush=True)
        logger.error("%s\n%s", safe_msg, "\n".join(f"  - {action}" for action in safe_actions))
        raise SystemExit(1)

    logger.info("MCP server ready: all checks passed.")
    yield


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
    logger.debug("[Tool] setup_check: running diagnostics on server configuration.")
    from spotify_mcp.wizard.state import collect_report

    return collect_report()


register_prompts(mcp)
db_crud.register(mcp)
spotify_control.register(mcp)


def main() -> None:
    mcp.run(transport="stdio")
