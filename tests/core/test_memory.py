"""Tests for the memory layer (Stage 4)."""
import uuid
import pytest
from spotify_core.memory import get_checkpointer, get_store, get_user_namespace


class TestGetUserNamespace:
    def test_preferences_namespace(self):
        ns = get_user_namespace("alice", "preferences")
        assert ns == ("user:alice", "preferences")

    def test_history_facts_namespace(self):
        ns = get_user_namespace("bob", "history_facts")
        assert ns == ("user:bob", "history_facts")

    def test_feedback_namespace(self):
        ns = get_user_namespace("carol", "feedback")
        assert ns == ("user:carol", "feedback")


class TestGetCheckpointer:
    def test_returns_sqlite_saver(self, tmp_path):
        from langgraph.checkpoint.sqlite import SqliteSaver
        db = str(tmp_path / "checkpoints.db")
        with get_checkpointer(db) as cp:
            assert isinstance(cp, SqliteSaver)

    def test_memory_isolation_across_threads(self, tmp_path):
        """Different thread_ids must produce independent state."""
        from langgraph.checkpoint.base import CheckpointMetadata

        db = str(tmp_path / "checkpoints.db")

        thread_a = {"configurable": {"thread_id": "thread-a", "checkpoint_ns": ""}}
        thread_b = {"configurable": {"thread_id": "thread-b", "checkpoint_ns": ""}}

        checkpoint_a = {
            "v": 1,
            "id": str(uuid.uuid4()),
            "ts": "2024-01-01T00:00:00+00:00",
            "channel_values": {"input": "hello from thread A"},
            "channel_versions": {"input": 1},
            "versions_seen": {},
            "pending_sends": [],
        }
        metadata: CheckpointMetadata = {"source": "input", "step": 0, "writes": None, "parents": {}}

        with get_checkpointer(db) as saver:
            saver.put(thread_a, checkpoint_a, metadata, {})
            result_b = saver.get(thread_b)

        assert result_b is None, "Thread B should see no state from Thread A"


class TestGetStore:
    def test_returns_sqlite_store(self, tmp_path):
        from langgraph.store.sqlite import SqliteStore
        db = str(tmp_path / "ltm.db")
        with get_store(db) as store:
            assert isinstance(store, SqliteStore)

    def test_ltm_persists_across_thread_ids(self, tmp_path):
        """Preference written once must be readable in the same store instance."""
        db = str(tmp_path / "ltm.db")
        ns = get_user_namespace("alice", "preferences")

        with get_store(db) as store:
            store.put(ns, "genre", {"value": "jazz"})
            result = store.get(ns, "genre")

        assert result is not None
        assert result.value == {"value": "jazz"}

    def test_namespace_isolation_between_users(self, tmp_path):
        """User A's preferences must not appear in User B's namespace."""
        db = str(tmp_path / "ltm.db")
        ns_a = get_user_namespace("alice", "preferences")
        ns_b = get_user_namespace("bob", "preferences")

        with get_store(db) as store:
            store.put(ns_a, "favorite_genre", {"value": "jazz"})
            result = store.get(ns_b, "favorite_genre")

        assert result is None, "Bob should not see Alice's preferences"
