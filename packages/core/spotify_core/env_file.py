"""Helper for reading and upserting key=value pairs in a .env file.

Public API
----------
read_key(path, key) -> Optional[str]
    Return the value for *key* in *path*, or None if file/key absent.

upsert(path, key, value) -> None
    Set *key* to *value* in *path*, creating the file (and parents) as needed.
    Existing keys are replaced in-place; new keys are appended.
    On non-Windows platforms the file is chmod'd to 0600.
"""
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Matches optional surrounding whitespace, a KEY, optional whitespace around =,
# and an optional value that may be wrapped in single or double quotes.
_LINE_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$"
)


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes and strip inner whitespace."""
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        value = value[1:-1]
    return value.strip()


def read_key(path: Path, key: str) -> Optional[str]:
    """Return the value associated with *key* in the .env file at *path*.

    Returns None if the file does not exist or the key is not found.
    """
    path = Path(path)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line)
        if m and m.group("key") == key:
            return _strip_quotes(m.group("value"))
    return None


def upsert(path: Path, key: str, value: str) -> None:
    """Set *key* to *value* in the .env file at *path*.

    - Creates *path* (and any missing parent directories) if absent.
    - Replaces an existing key in-place without disturbing other lines.
    - Appends the key if it is not already present.
    - Writes UTF-8 with a trailing newline.
    - On non-Windows platforms, applies chmod 0600 to the file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    new_line = f"{key}={value}"
    replaced = False
    updated: list[str] = []
    for line in lines:
        m = _LINE_RE.match(line)
        if m and m.group("key") == key:
            # All lines with matching key are replaced with a single new line.
            # If multiple lines with the same key exist, only the first is replaced
            # with new_line and subsequent matching lines are skipped entirely.
            if not replaced:
                updated.append(new_line)
                replaced = True
        else:
            updated.append(line)

    if not replaced:
        updated.append(new_line)

    content = "\n".join(updated) + "\n"
    path.write_text(content, encoding="utf-8")

    if sys.platform != "win32":
        os.chmod(path, 0o600)
