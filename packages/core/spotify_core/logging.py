import sys
from pathlib import Path
from loguru import logger

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def setup_logging(
    mode: str = "app",
    log_name: str | None = None,
    level: str = "DEBUG",
    stream=sys.stdout,
) -> Path:
    """Configure logging for app, test, or MCP server runs.

    For MCP stdio servers, pass stream=sys.stderr to avoid corrupting stdout.
    """
    from spotify_core import paths

    folder = "test" if mode == "test" else "app"
    prefix = log_name or ("test_debug" if mode == "test" else "app_debug")
    log_file = paths.data_dir() / "logs" / folder / f"{prefix}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(log_file, level=level, encoding="utf-8")
    logger.add(stream, level=level)
    return log_file


def setup_mcp_logging(log_name: str = "spotify_mcp", level: str = "DEBUG") -> Path:
    """Set up logging for MCP stdio servers (stream → stderr, never stdout).

    MCP stdio transport uses stdout for protocol messages — writing logs there
    corrupts the channel. This function always streams to stderr.
    """
    return setup_logging(log_name=log_name, level=level, stream=sys.stderr)
