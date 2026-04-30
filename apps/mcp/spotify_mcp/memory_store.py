"""MCP tools backed by the long-term memory store (data/ltm.db).

Backed by langgraph's SqliteStore so the same memory file can be shared with
the LangGraph agent in Phase 2 (see ARCHITECTURE.md §4.2).
"""
import logging
from typing import Annotated

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from spotify_mcp.config import DEFAULT_USER_ID, LTM_DB

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    # TODO: the memory schemas are still unstable. need to imporve error handling and validation here before opening to users.
    """Attach long-term memory tools to the given FastMCP server."""

    @mcp.tool(
        name="remember_preference",
        annotations={
            "title": "Store User Preference",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def remember_preference(
        key: Annotated[str, Field(min_length=1, max_length=100, description="Preference key, e.g. 'favorite_genre'.")],
        value: Annotated[str, Field(min_length=1, max_length=2000, description="Preference value as a string.")],
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Store a user preference in long-term memory. Persists across all future conversations.

        Writing the same key again overwrites the previous value.
        Use get_memory_summary to read back all stored preferences.
        """
        try:
            from spotify_core.memory import get_store, get_user_namespace
            ns = get_user_namespace(user_id, "preferences")
            with get_store(LTM_DB) as store:
                store.put(ns, key, {"value": value})
            return {"status": "saved", "key": key, "value": value}
        except Exception as exc:
            logger.error("remember_preference failed: %s", exc)
            return {"error": str(exc)}

    @mcp.tool(
        name="get_memory_summary",
        annotations={
            "title": "Get Long-Term Memory Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def get_memory_summary(
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Return all stored preferences, history facts, and feedback for a user from long-term memory.

        Use this at the start of a conversation to recall what is known about the user.
        Store new information with remember_preference.
        """
        try:
            from spotify_core.memory import get_store, get_user_namespace
            summary: dict = {}
            with get_store(LTM_DB) as store:
                for key in ("preferences", "history_facts", "feedback"):
                    ns = get_user_namespace(user_id, key)
                    items = store.search(ns)
                    summary[key] = {item.key: item.value for item in items}
            return summary
        except Exception as exc:
            logger.error("get_memory_summary failed: %s", exc)
            return {"error": str(exc)}
