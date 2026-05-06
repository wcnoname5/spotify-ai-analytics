"""Tests for spotify_core.env_file — .env read/upsert helper."""
import os
import sys
from pathlib import Path

import pytest

from spotify_core import env_file


# ---------------------------------------------------------------------------
# read_key
# ---------------------------------------------------------------------------

def test_read_key_missing_file_returns_none(tmp_path):
    result = env_file.read_key(tmp_path / "nonexistent.env", "ANY_KEY")
    assert result is None


def test_read_key_present_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SPOTIFY_CLIENT_ID=abc123\n", encoding="utf-8")
    assert env_file.read_key(env, "SPOTIFY_CLIENT_ID") == "abc123"


def test_read_key_strips_quotes_and_whitespace(tmp_path):
    env = tmp_path / ".env"
    env.write_text('TOKEN = "  hello world  "\n', encoding="utf-8")
    assert env_file.read_key(env, "TOKEN") == "hello world"


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------

def test_upsert_creates_missing_file(tmp_path):
    env = tmp_path / "subdir" / ".env"
    env_file.upsert(env, "MY_KEY", "my_value")
    assert env.exists()
    assert env_file.read_key(env, "MY_KEY") == "my_value"


def test_upsert_replaces_existing_key_preserves_others(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=old_value\nBAR=keep_me\n", encoding="utf-8")
    env_file.upsert(env, "FOO", "new_value")
    assert env_file.read_key(env, "FOO") == "new_value"
    assert env_file.read_key(env, "BAR") == "keep_me"


def test_upsert_appends_missing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXISTING=yes\n", encoding="utf-8")
    env_file.upsert(env, "NEW_KEY", "new_val")
    assert env_file.read_key(env, "EXISTING") == "yes"
    assert env_file.read_key(env, "NEW_KEY") == "new_val"


def test_upsert_replaces_all_duplicate_keys(tmp_path):
    """When a key appears multiple times, upsert replaces ALL occurrences."""
    env = tmp_path / ".env"
    env.write_text("FOO=first\nBAR=keep\nFOO=second\n", encoding="utf-8")
    env_file.upsert(env, "FOO", "new_value")

    # All FOO lines should be replaced with a single new line
    content = env.read_text(encoding="utf-8")
    foo_count = content.count("FOO=")
    assert foo_count == 1, f"Expected exactly 1 FOO= line, found {foo_count}"

    # Verify the new value and that BAR is preserved
    assert env_file.read_key(env, "FOO") == "new_value"
    assert env_file.read_key(env, "BAR") == "keep"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 not enforced on Windows")
def test_upsert_sets_mode_0600(tmp_path):
    env = tmp_path / ".env"
    env_file.upsert(env, "SECRET", "value")
    mode = oct(env.stat().st_mode & 0o777)
    assert mode == oct(0o600), f"Expected 0600, got {mode}"
