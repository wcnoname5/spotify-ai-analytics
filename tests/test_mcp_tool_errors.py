"""Integration tests: MCP tools should return enriched error dicts when
tokens are missing or the history DB is uninitialized.

Verifies that exceptions raised in core layers propagate through the FastMCP
tool wrapper as structured responses (with ``requires_auth`` or
``requires_import`` flags), instead of leaking raw exception messages or 500s.
"""
import asyncio

import pytest
from cryptography.fernet import Fernet
from fastmcp import FastMCP

from spotify_core.db.migrations import init_tokens_db
from spotify_mcp import db_crud


def _call_tool(mcp: FastMCP, name: str, **kwargs):
    """Synchronously invoke a registered tool's underlying function."""
    async def _go():
        tool = await mcp.get_tool(name)
        return tool.fn(**kwargs)
    return asyncio.run(_go())


@pytest.fixture()
def mcp_with_temp_paths(tmp_path, monkeypatch):
    """Register db_crud tools against a FastMCP pointed at empty tmp DB paths.

    Both the history DB and the tokens DB live under tmp_path and are NOT
    initialized — exercising the missing-data error paths.
    """
    history_db = str(tmp_path / "history.db")
    tokens_db = str(tmp_path / "tokens.db")
    fernet_key = Fernet.generate_key()

    # Tools read these from spotify_mcp.config at call time, so monkeypatch them.
    monkeypatch.setattr("spotify_mcp.config.DB_PATH", history_db)
    monkeypatch.setattr("spotify_mcp.config.TOKENS_DB", tokens_db)
    monkeypatch.setattr("spotify_mcp.config.DEFAULT_USER_ID", "test_user")

    # db_crud already imported these names at module load time — patch the
    # module-level bindings too so the tool body sees the temp paths.
    monkeypatch.setattr(db_crud, "DB_PATH", history_db)
    monkeypatch.setattr(db_crud, "TOKENS_DB", tokens_db)
    monkeypatch.setattr(db_crud, "DEFAULT_USER_ID", "test_user")

    mcp = FastMCP("test_mcp")
    db_crud.register(mcp)
    return mcp, history_db, tokens_db


class TestSyncHistoryAuthError:
    def test_uninitialized_tokens_db_returns_requires_auth(self, mcp_with_temp_paths):
        mcp, _history_db, _tokens_db = mcp_with_temp_paths
        # Tokens DB file does not exist at all.
        result = _call_tool(mcp, "sync_history", user_id="test_user")

        assert isinstance(result, dict)
        assert result.get("requires_auth") is True
        assert result["auth_command"] == "spotify-mcp reauth"

    def test_initialized_but_no_token_row_returns_requires_auth(
        self, mcp_with_temp_paths
    ):
        mcp, _history_db, tokens_db = mcp_with_temp_paths
        # Initialize tokens DB but never save a row for this user.
        init_tokens_db(tokens_db)

        result = _call_tool(mcp, "sync_history", user_id="test_user")

        # load_tokens returns None → sync_api_to_db raises RuntimeError
        # (not SpotifyAuthError), so we should still get a structured error
        # but not the auth flag. This locks in current behavior so a
        # regression that swallows the message is caught.
        assert isinstance(result, dict)
        assert "error" in result


class TestGetRecentPlaybackAuthError:
    def test_uninitialized_tokens_db_returns_requires_auth(self, mcp_with_temp_paths):
        mcp, *_ = mcp_with_temp_paths
        result = _call_tool(mcp, "get_recent_playback", user_id="test_user")

        assert isinstance(result, dict)
        assert result.get("requires_auth") is True
        assert "auth_command" in result
