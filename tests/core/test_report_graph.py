"""Tests for the report graph using a scripted fake chat model."""
from langchain_core.messages import AIMessage

from spotify_core.db.migrations import get_connection, init_history_db
from spotify_core.report.graph import generate_report
from spotify_core.report.state import ReviewVerdict


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


class _FakeStructured:
    """A structured-output fake model — pops scripted ReviewVerdicts."""
    def __init__(self, verdicts):
        self._verdicts = verdicts

    def invoke(self, messages, config=None):
        return self._verdicts.pop(0)


class FakeChatModel:
    """Scripted stand-in for a BaseChatModel.

    draft_responses: AIMessages returned by the drafter's bound model, in order.
    review_verdicts: ReviewVerdicts returned by the reviewer, in order.
    The bound/structured wrappers share the underlying lists, so pops persist
    across successive drafter/reviewer passes.
    """
    def __init__(self, draft_responses, review_verdicts):
        self._draft_responses = list(draft_responses)
        self._review_verdicts = list(review_verdicts)

    def bind_tools(self, tools):
        return _FakeBound(self._draft_responses)

    def with_structured_output(self, schema):
        return _FakeStructured(self._review_verdicts)


def test_drafter_records_tool_calls_and_reviewer_approves(tmp_path):
    db = _history_db(tmp_path)
    model = FakeChatModel(
        draft_responses=[
            AIMessage(content="", tool_calls=[
                _tool_call("c1", "get_top_artists",
                           {"start_date": "2024-01-01", "end_date": "2024-01-31"})
            ]),
            AIMessage(content="# 收聽回顧\n你聽了 A。"),
        ],
        review_verdicts=[ReviewVerdict(approved=True, feedback="")],
    )
    result = generate_report(
        style="listening_review", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    assert result.approved is True
    assert result.revision_count == 0
    assert result.text == "# 收聽回顧\n你聽了 A。"
    assert [r.name for r in result.tool_log] == ["get_top_artists"]
    assert result.tool_log[0].success is True
    assert result.trace_url is None


def test_reviewer_rejects_once_then_approves(tmp_path):
    db = _history_db(tmp_path)
    model = FakeChatModel(
        draft_responses=[
            AIMessage(content="草稿一"),
            AIMessage(content="草稿二"),
        ],
        review_verdicts=[
            ReviewVerdict(approved=False, feedback="不夠毒舌"),
            ReviewVerdict(approved=True, feedback=""),
        ],
    )
    result = generate_report(
        style="roast", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    assert result.approved is True
    assert result.revision_count == 1
    assert result.text == "草稿二"


def test_revision_cap_terminates(tmp_path):
    db = _history_db(tmp_path)
    model = FakeChatModel(
        draft_responses=[
            AIMessage(content="草稿一"),
            AIMessage(content="草稿二"),
            AIMessage(content="草稿三"),
        ],
        review_verdicts=[
            ReviewVerdict(approved=False, feedback="再修"),
            ReviewVerdict(approved=False, feedback="再修"),
            ReviewVerdict(approved=False, feedback="再修"),
        ],
    )
    result = generate_report(
        style="roast", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    # Cap is 2 rejections: 1 initial draft + 1 revision, then a forced end.
    assert result.approved is False
    assert result.revision_count == 2
    assert result.text == "草稿二"


def test_drafter_hits_tool_iteration_cap(tmp_path):
    db = _history_db(tmp_path)
    rng_args = {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    # 10 consecutive tool-call responses, each also carrying prose content, so
    # the drafter exhausts the iteration cap without ever returning a plain draft.
    draft_responses = [
        AIMessage(content="草稿", tool_calls=[
            _tool_call(f"c{i}", "get_top_artists", rng_args)
        ])
        for i in range(10)
    ]
    model = FakeChatModel(
        draft_responses=draft_responses,
        review_verdicts=[ReviewVerdict(approved=True, feedback="")],
    )
    result = generate_report(
        style="listening_review", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    # On hitting the cap the draft must be the last AIMessage's prose content,
    # never the raw tool-result JSON of the trailing ToolMessage.
    assert result.text == "草稿"
    assert result.approved is True
