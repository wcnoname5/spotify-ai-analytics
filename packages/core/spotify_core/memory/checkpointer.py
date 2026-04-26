"""Short-term conversation memory via LangGraph SqliteSaver.

SqliteSaver resets on each new thread_id (new conversation).
Do NOT store user preferences here — use store.py instead.
"""
from langgraph.checkpoint.sqlite import SqliteSaver


def get_checkpointer(db_path: str) -> SqliteSaver:
    """Return a SqliteSaver bound to db_path.

    Args:
        db_path: Path to the SQLite file (e.g. "data/checkpoints.db").

    Returns:
        SqliteSaver instance for use as workflow checkpointer.
    """
    return SqliteSaver.from_conn_string(db_path)
