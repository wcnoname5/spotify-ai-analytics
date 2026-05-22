---
name: python-logging
description: Use when setting up, configuring, or adding logging to a Python project — new modules, new functions, MCP stdio servers, or questions about log levels, log file location, or logging structure.
---

# Python Logging Convention (loguru)

## Core Rule: One Central Module Owns All Config

Logging is configured exactly once, in a dedicated module (e.g., `your_package/logging.py`). Every other file just does:

```python
from loguru import logger
```

No other file calls `logger.remove()`, `logger.add()`, or touches log levels.

## The Central Logging Module

```python
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
    from your_package import paths  # lazy import to avoid circular dependency

    folder = "test" if mode == "test" else "app"
    prefix = log_name or ("test_debug" if mode == "test" else "app_debug")
    log_file = paths.data_dir() / "logs" / folder / f"{prefix}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(log_file, level=level, encoding="utf-8")
    logger.add(stream, level=level)
    return log_file


def setup_mcp_logging(log_name: str = "my_mcp", level: str = "DEBUG") -> Path:
    """Set up logging for MCP stdio servers (stream → stderr, never stdout).

    MCP stdio transport uses stdout for protocol messages — writing logs there
    corrupts the channel. This function always streams to stderr.
    """
    return setup_logging(log_name=log_name, level=level, stream=sys.stderr)
```

## Log Directory Layout

```
logs/
├── app/          # Normal app and MCP server runs — one persistent file per service
└── test/         # Pytest runs only
```

Add `logs/` to `.gitignore`. No timestamps in filenames — one log file per named service, appended on each run.

## Calling the Setup Function

Call it exactly once, as early as possible in the process — before any imports that might emit logs.

```python
import os
from your_package.logging import setup_logging, setup_mcp_logging

# Normal app or pytest conftest
setup_logging(mode="app", log_name="my_service", level=os.getenv("LOG_LEVEL", "DEBUG").upper())

# MCP stdio server — must use stderr; stdout is the protocol channel
setup_mcp_logging(log_name="my_mcp", level=os.getenv("LOG_LEVEL", "DEBUG").upper())
```

## Every Module Gets a Logger

```python
from loguru import logger
```

That's it — no `getLogger(__name__)`, no module-level setup. loguru's built-in format already includes timestamp, level, module name (`{name}`), function, line, and message. The `{name}` field auto-captures the calling module's dotted path.

**Do not** create per-method or per-class loggers. Use `logger.bind(key=value)` if you need to attach context to a specific call:

```python
logger.bind(method="fetch_user").debug("user_id={}", user_id)
```

## Every Function Logs Meaningfully

```python
def fetch_user(user_id: str) -> dict:
    logger.debug("fetch_user: user_id={}", user_id)
    try:
        result = db.get(user_id)
        logger.info("fetch_user success: user_id={}", user_id)
        return result
    except Exception as exc:
        logger.error("fetch_user failed: user_id={} error={}", user_id, exc)
        raise
```

| Level | When to use |
|---|---|
| `DEBUG` | Entry, intermediate state, tracing values |
| `INFO` | Successful completion of a meaningful operation |
| `WARNING` | Recoverable issue, skipped item, degraded behavior |
| `ERROR` | Caught failure — operation failed, program continues |
| `logger.exception(msg)` | Like ERROR but also dumps the traceback; use inside `except` |

Use `logger.error("msg: {}", value)` (`{}` format), not f-strings — loguru only renders the string if that level is active.
