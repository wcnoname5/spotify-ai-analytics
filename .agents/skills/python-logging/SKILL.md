---
name: python-logging
description: Use when setting up, configuring, or adding logging to a Python project — new modules, new functions, MCP stdio servers, or questions about log levels, log file location, or logging structure.
---

# Python Logging Convention

## Core Rule: One Central Module Owns All Config

Logging is configured exactly once, in a dedicated module (e.g., `your_package/logging.py`). Every other file just does:

```python
import logging
logger = logging.getLogger(__name__)
```

No other file calls `basicConfig`, adds handlers, or sets levels.

## The Central Logging Module

```python
import logging
import sys
from datetime import datetime
from pathlib import Path


def _find_project_root(anchor: str = ".env.example") -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / anchor).exists():
            return parent
    raise RuntimeError(f"Could not find project root (no '{anchor}' found)")


PROJECT_ROOT = _find_project_root()

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(
    mode: str = "app",
    log_name: str | None = None,
    level: int = logging.DEBUG,
    stream=sys.stdout,
) -> Path:
    """Configure logging for app, test, or MCP server runs.

    For MCP stdio servers, pass stream=sys.stderr to avoid corrupting stdout.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = "test" if mode == "test" else "app"
    prefix = log_name or ("test_debug" if mode == "test" else "app_debug")
    log_file = PROJECT_ROOT / "logs" / folder / f"{prefix}-{timestamp}.log"
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
```

## Log Directory Layout

```
logs/
├── app/          # Normal app and MCP server runs
└── test/         # Pytest runs only
```

Add `logs/` to `.gitignore`. Use an anchor-file search (above) rather than chaining `.parent` — the chain breaks silently if files move.

## Calling the Setup Function

Call it exactly once, as early as possible in the process — before any imports that might emit logs.

```python
import os, logging

# Normal app or pytest conftest
from your_package.logging import setup_logging
setup_logging(mode="app", log_name="my_service",
              level=getattr(logging, os.getenv("LOG_LEVEL", "DEBUG")))

# MCP stdio server — must use stderr; stdout is the protocol channel
setup_logging(log_name="my_mcp", stream=sys.stderr,
              level=getattr(logging, os.getenv("LOG_LEVEL", "DEBUG")))
```

## Every Module Gets a Logger

```python
import logging
logger = logging.getLogger(__name__)
```

`__name__` resolves to the module's dotted path (e.g., `myapp.db.queries`), which appears in every log line.

## Every Function Logs Meaningfully

```python
def fetch_user(user_id: str) -> dict:
    logger.debug("fetch_user: user_id=%s", user_id)
    try:
        result = db.get(user_id)
        logger.info("fetch_user success: user_id=%s", user_id)
        return result
    except Exception as exc:
        logger.error("fetch_user failed: user_id=%s error=%s", user_id, exc)
        raise
```

| Level | When to use |
|---|---|
| `DEBUG` | Entry, intermediate state, tracing values |
| `INFO` | Successful completion of a meaningful operation |
| `WARNING` | Recoverable issue, skipped item, degraded behavior |
| `ERROR` | Caught failure — operation failed, program continues |
| `logger.exception(...)` | Like ERROR but also dumps the traceback; use inside `except` |

Use `logger.error("msg: %s", value)` (% formatting), not f-strings — the string is only rendered if that level is emitted.
