import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 on Windows once at import — covers both stdout and stderr.
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _find_project_root(anchor: str = ".env.example") -> Path:
    """Walk upward from this file until an anchor file is found."""
    for parent in Path(__file__).resolve().parents:
        if (parent / anchor).exists():
            return parent
    raise RuntimeError(f"Could not find project root (no '{anchor}' found)")


PROJECT_ROOT = _find_project_root()

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _setup(log_file: Path, level: int, stream) -> Path:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(stream),
        ],
        force=True,
    )
    return log_file


def setup_logging(
    mode: str = "app",
    log_name: str | None = None,
    level: int = logging.DEBUG,
    _stream=None,
) -> Path:
    """Set up logging for normal app and test runs (stream → stdout).

    Args:
        mode: "app" for normal usage, "test" for pytest runs.
        log_name: Optional filename prefix.
        level: Root log level.

    Returns:
        Path of the log file opened.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = "test" if mode == "test" else "app"
    prefix = log_name or ("test_debug" if mode == "test" else "app_debug")
    log_file = PROJECT_ROOT / "logs" / folder / f"{prefix}-{timestamp}.log"
    return _setup(log_file, level, _stream or sys.stdout)


def setup_mcp_logging(log_name: str = "spotify_mcp", level: int = logging.DEBUG) -> Path:
    """Set up logging for MCP stdio servers (stream → stderr, never stdout).

    MCP stdio transport uses stdout for protocol messages — writing logs there
    corrupts the channel. This function always streams to stderr.

    Args:
        log_name: Filename prefix.
        level: Root log level.

    Returns:
        Path of the log file opened.
    """
    return setup_logging(log_name=log_name, level=level, _stream=sys.stderr)
