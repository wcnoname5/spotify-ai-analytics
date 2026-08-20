"""Tests for the report agent using a scripted fake chat model."""

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage

from spotify_core.db.migrations import get_connection, init_history_db
from spotify_core.report.agent import generate_report


@pytest.fixture(autouse=True)
def _disable_langfuse_tracing(monkeypatch):
    # langfuse_configured is a property, so we patch the underlying keys
    monkeypatch.setattr("spotify_core.config.settings.langfuse_public_key", None)
    monkeypatch.setattr("spotify_core.config.settings.langfuse_secret_key", None)
    monkeypatch.setattr("spotify_core.config.settings.langfuse_base_url", None)


def _seed(db_path, rows):
    conn = get_connection(db_path)
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'json_import')",
                (r["id"], r["id"], "T", "A", r["played_at"], r["ms_played"]),
            )
    conn.close()


def _history_db(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [{"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000}])
    return db


def _tool_call(call_id, name, args):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class _FakeBound:
    """A tool-bound fake model — pops scripted AIMessages on each invoke."""
    def __init__(self, responses):
        self._responses = responses

    def invoke(self, messages, config=None):
        return self._responses.pop(0)


class FakeChatModel:
    """Scripted stand-in for a BaseChatModel: `responses` are returned in order."""
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools, **kwargs):
        return _FakeBound(self._responses)


_RANGE = {"start_date": "2024-01-01", "end_date": "2024-01-31"}


def test_calls_tools_then_returns_the_article(tmp_path):
    db = _history_db(tmp_path)
    model = FakeChatModel([
        AIMessage(content="", tool_calls=[
            _tool_call("c1", "get_top_artists", _RANGE)
        ]),
        AIMessage(content="# 收聽回顧\n你聽了 A。"),
    ])
    assert generate_report(
        style="listening_review", db_path=db, model=model, **_RANGE
    ) == "# 收聽回顧\n你聽了 A。"


def test_model_call_cap_fails_loudly(tmp_path):
    """Burning the whole call budget without finishing the article is a failure, not
    a half-written report to salvage — the app would save whatever we returned."""
    db = _history_db(tmp_path)
    model = FakeChatModel([
        AIMessage(content="草稿", tool_calls=[
            _tool_call(f"c{i}", "get_top_artists", _RANGE)
        ])
        for i in range(11)
    ])
    with pytest.raises(ModelCallLimitExceededError):
        generate_report(style="roast", db_path=db, model=model, **_RANGE)


def test_no_prose_raises(tmp_path):
    """An empty article must fail loudly — the CLI would otherwise print nothing
    and the caller would save an empty report row."""
    db = _history_db(tmp_path)
    model = FakeChatModel([AIMessage(content="")])
    with pytest.raises(RuntimeError, match="no prose"):
        generate_report(style="roast", db_path=db, model=model, **_RANGE)
