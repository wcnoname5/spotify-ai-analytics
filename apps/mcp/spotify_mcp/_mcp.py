"""FastMCP application — mcp instance, tool registrations, and main().

This module owns the FastMCP app object so it can be imported by both the
development entry point (apps/mcp/server.py) and the `spotify-mcp serve`
CLI command without duplicating server logic.
"""
import sys
from loguru import logger
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from spotify_mcp import db_crud, spotify_control
from spotify_mcp.prompts import register_prompts

@asynccontextmanager
async def lifespan(server: FastMCP):
    from spotify_mcp.cli import _collect_report as collect_report

    report = collect_report()
    # `ready` already excludes the non-blocking "fill the local cache" action.
    if not report["ready"]:
        blocking = report["actions_needed"]
        msg = "spotify-mcp not configured. Finish setup in the desktop app."

        def _ascii_safe(s: str) -> str:
            # TODO: remove this and drop all em-dash directly in all .py files to avoid the UnicodeDecodeError in Windows consoles (cp1252) when printing to stderr.
            # Replace Unicode dashes with ASCII hyphen so Windows consoles
            # (cp1252) don't produce un-decodable bytes in the stderr stream.
            return s.replace("—", "-").replace("–", "-")

        safe_msg = _ascii_safe(msg)
        print(safe_msg, file=sys.stderr, flush=True)
        safe_actions = [_ascii_safe(action) for action in blocking]
        for action in blocking:
            print(_ascii_safe(f"  - {action}"), file=sys.stderr, flush=True)
        logger.error("{}\n{}", safe_msg, "\n".join(f"  - {action}" for action in safe_actions))
        raise SystemExit(1)

    # Pull D1 into the local cache before serving. c..f. `syncOnStartup()` in dashboard
    # Fail-soft on purpose: no Worker configured, or no network, must
    # still leave a usable server reading the cache it already has.
    try:
        from spotify_mcp import cloud

        cloud.pull(quiet=True)
    except Exception as exc:  # noqa: BLE001 - never let a refresh stop the server
        logger.warning("Startup sync skipped ({}): serving cached data.", exc)

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
    from spotify_mcp.cli import _collect_report as collect_report

    return collect_report()


register_prompts(mcp)
db_crud.register(mcp)
spotify_control.register(mcp)


def main() -> None:
    mcp.run(transport="stdio")
