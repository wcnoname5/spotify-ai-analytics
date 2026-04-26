"""Long-term memory (LTM) via LangGraph SqliteStore.

SqliteStore persists across all thread_ids and sessions.
User preferences, feedback, and history facts go here — never in checkpointer.

Namespace convention:
    ("user:{user_id}", "preferences")
    ("user:{user_id}", "history_facts")
    ("user:{user_id}", "feedback")
"""
from typing import Tuple
from langgraph.store.sqlite import SqliteStore


def get_store(db_path: str) -> SqliteStore:
    """Return a SqliteStore bound to db_path.

    Args:
        db_path: Path to the SQLite file (e.g. "data/ltm.db").

    Returns:
        SqliteStore instance for use as workflow store.
    """
    return SqliteStore.from_conn_string(db_path)


def get_user_namespace(user_id: str, key: str) -> Tuple[str, str]:
    """Return the canonical LTM namespace tuple for a user + key.

    Args:
        user_id: Spotify user ID.
        key: One of "preferences", "history_facts", "feedback".

    Returns:
        Namespace tuple, e.g. ("user:alice", "preferences").
    """
    return (f"user:{user_id}", key)
