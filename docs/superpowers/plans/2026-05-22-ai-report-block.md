# AI Report Block Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI listening-report section to the dashboard — a minimal LangGraph drafter/reviewer graph that writes an opinionated analytical article (4 fixed styles) from the user's local listening data.

**Architecture:** A new pure `packages/core/spotify_core/report/` package holds a 2-node LangGraph (drafter + reviewer, one conditional edge). The drafter calls in-process LangChain `@tool` wrappers around `db/queries.py` in a bounded loop; the reviewer judges via structured output. `generate_report(...)` is the single entry point. A new Streamlit section `apps/web/ui/ai_block.py` calls it. LLM providers are swappable via `BaseChatModel` (Google implemented; OpenAI/Anthropic skeletons). Langfuse traces runs when its keys are present, and the run's trace URL is surfaced back to the UI.

**Tech Stack:** Python 3.12+, LangGraph 1.0, LangChain Core 1.x, `langchain-google-genai`, `langfuse` (optional), `loguru`, Streamlit, pytest, `uv` workspace.

**Spec:** `docs/superpowers/specs/2026-05-21-ai-report-block-design.md`

**Scope decisions (confirmed with the user):**
- The in-app settings panel (spec §10.2) is **deferred** — v1 reads provider keys from `.env` only.
- The period playlist (spec feature 3 / §8) is **split to a follow-up plan** — this plan ships only the report engine (features 1 & 2).
- The three trend granularities are exposed as **three separate tools** (`get_daily_trend`, `get_weekly_trend`, `get_monthly_trend`); the LLM picks which to call, rather than a span-based auto-selection.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/core/pyproject.toml` | **Modify** — add a `report` optional-dependency extra |
| `pyproject.toml` (root) | **Modify** — add `langfuse` and `loguru` so `uv sync` installs them |
| `.env.example` | **Modify** — document the new optional env vars |
| `CLAUDE.md` | **Modify** — document the new env vars |
| `packages/core/spotify_core/report/__init__.py` | **Create** — package marker |
| `packages/core/spotify_core/report/state.py` | **Create** — `ReportState`, `ToolCallRecord`, `ReviewVerdict`, `ReportResult`, `extract_tool_log` |
| `packages/core/spotify_core/report/tools.py` | **Create** — `make_report_tools(db_path)` |
| `packages/core/spotify_core/report/models.py` | **Create** — `build_chat_model(provider, model)` |
| `packages/core/spotify_core/report/prompts.py` | **Create** — 4 drafter style templates + reviewer rubric |
| `packages/core/spotify_core/report/observability.py` | **Create** — `get_langfuse_callbacks()`, `get_trace_url()` |
| `packages/core/spotify_core/report/nodes.py` | **Create** — `make_report_nodes(tools)` → drafter/reviewer/route |
| `packages/core/spotify_core/report/graph.py` | **Create** — `build_report_graph(tools)`, `generate_report(...)` |
| `apps/web/spotify_web/config.py` | **Modify** — add `get_llm_config()` |
| `apps/web/ui/ai_block.py` | **Create** — Streamlit AI report section |
| `apps/web/ui/dashboard.py` | **Modify** — call `render_ai_block` at the end of `render_dashboard()` |
| `tests/core/test_report_state.py` | **Create** |
| `tests/core/test_report_tools.py` | **Create** |
| `tests/core/test_report_models.py` | **Create** |
| `tests/core/test_report_observability.py` | **Create** |
| `tests/core/test_report_graph.py` | **Create** |
| `tests/web/test_web_config.py` | **Create** |

All test commands use `uv run` (CLAUDE.md). Commits use conventional-commit prefixes. All new modules use **loguru** — `from loguru import logger`, `{}` placeholders, no stdlib logging, no `print()`.

---

## Task 1: Dependencies, env docs, and package scaffold

Adds `langfuse` and `loguru`, documents new env vars, creates the empty `report` package.

- [ ] **Step 1: Add `langfuse` and `loguru` to the root dependencies**

In `pyproject.toml`, in the `[project]` `dependencies` list, replace:

```toml
    "langgraph==1.0.5",
    "numpy>=2.4.0",
```

with:

```toml
    "langgraph==1.0.5",
    "langfuse>=3.0",
    "loguru>=0.7",
    "numpy>=2.4.0",
```

- [ ] **Step 2: Add the `report` extra to the core package**

In `packages/core/pyproject.toml`, replace the `[project.optional-dependencies]` block:

```toml
[project.optional-dependencies]
agent = [
    "langgraph>=1.0",
    "langchain-core>=1.0",
    "langchain-openai>=1.0",
    "langchain-google-genai>=4.0",
]
```

with:

```toml
[project.optional-dependencies]
agent = [
    "langgraph>=1.0",
    "langchain-core>=1.0",
    "langchain-openai>=1.0",
    "langchain-google-genai>=4.0",
]
report = [
    "langgraph>=1.0",
    "langchain-core>=1.0",
    "langchain-google-genai>=4.0",
    "langfuse>=3.0",
    "loguru>=0.7",
]
```

- [ ] **Step 3: Install and verify**

```bash
uv sync
uv run python -c "import langfuse, langgraph, langchain_google_genai, loguru; print('ok')"
```

- [ ] **Step 4: Document the new env vars in `.env.example`**

In `.env.example`, replace:

```bash
# Or use gemini
GEMINI_API_KEY=your_gemini_api_key_here
```

with:

```bash
# Or use gemini
GEMINI_API_KEY=your_gemini_api_key_here

# AI report block (apps/web) — all optional; absence degrades gracefully
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
```

- [ ] **Step 5: Document the new env vars in `CLAUDE.md`**

In `CLAUDE.md`, in the "Environment Variables" section, replace:

```bash
# Required for web only
GEMINI_API_KEY=       # or OPENAI_API_KEY

# Optional
LOG_LEVEL=INFO        # DEBUG for verbose output
```

with:

```bash
# Required for web only
GEMINI_API_KEY=       # or OPENAI_API_KEY

# AI report block (apps/web) — all optional; absence degrades gracefully
GOOGLE_API_KEY=        # LLM provider for the AI report block (v1)
LANGFUSE_PUBLIC_KEY=   # Langfuse tracing (all 3 keys needed, or none)
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=

# Optional
LOG_LEVEL=INFO        # DEBUG for verbose output
```

- [ ] **Step 6: Create the report package marker**

Create `packages/core/spotify_core/report/__init__.py`:

```python
"""LLM-based listening-report generation.

A minimal LangGraph drafter/reviewer graph that writes an opinionated
analytical article from the user's local listening data.
"""
```

- [ ] **Step 7: Commit**

```bash
git commit -m "chore: scaffold report package and add langfuse + loguru dependencies"
```

---

## Task 2: Report state — `report/state.py`

State types and the `extract_tool_log` projection helper. Pure module — no LangGraph imports.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/core/test_report_state.py`:

```python
"""Tests for spotify_core.report.state — state types and extract_tool_log."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from spotify_core.report.state import ToolCallRecord, extract_tool_log


def _ai_with_call(call_id, name, args):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def test_extract_tool_log_pairs_calls_and_results():
    messages = [
        HumanMessage(content="hi"),
        _ai_with_call("c1", "get_top_artists", {"start_date": "2024-01-01"}),
        ToolMessage(
            content="[{'artist': 'A'}]", tool_call_id="c1",
            name="get_top_artists", status="success",
        ),
        AIMessage(content="final draft"),
    ]
    log = extract_tool_log(messages)
    assert len(log) == 1
    assert isinstance(log[0], ToolCallRecord)
    assert log[0].name == "get_top_artists"
    assert log[0].args == {"start_date": "2024-01-01"}
    assert log[0].success is True
    assert log[0].error is None


def test_extract_tool_log_marks_errors():
    messages = [
        _ai_with_call("c1", "get_top_tracks", {}),
        ToolMessage(
            content="boom", tool_call_id="c1",
            name="get_top_tracks", status="error",
        ),
    ]
    log = extract_tool_log(messages)
    assert log[0].success is False
    assert log[0].error == "boom"


def test_extract_tool_log_empty_when_no_tool_calls():
    assert extract_tool_log([AIMessage(content="just a draft")]) == []
```

- [ ] **Step 2: Implement `state.py`**

Create `packages/core/spotify_core/report/state.py`:

```python
"""State types and helpers for the report graph.

Pure module — no LangGraph/LLM-runtime imports. The graph nodes import these
types; keeping them here lets tests construct and assert on state directly.
"""
from dataclasses import dataclass, field
from typing import Optional, TypedDict

from loguru import logger
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import BaseModel, Field

_RESULT_TRUNCATE = 500


@dataclass
class ToolCallRecord:
    """One tool call the drafter made — a projection of an AIMessage/ToolMessage pair."""
    name: str
    args: dict
    result: str
    success: bool
    error: Optional[str] = None


class ReviewVerdict(BaseModel):
    """Structured output of the reviewer node."""
    approved: bool = Field(description="True if the draft is good enough to ship.")
    feedback: str = Field(
        default="",
        description="Concrete, actionable revision notes. Empty when approved.",
    )


class ReportState(TypedDict):
    """Mutable state threaded through the report graph."""
    style: str
    start_date: str
    end_date: str
    draft: str
    review_feedback: str
    revision_count: int
    approved: bool
    tool_log: list[ToolCallRecord]
    final_report: str


@dataclass
class ReportResult:
    """UI-facing result returned by generate_report."""
    text: str
    style: str
    revision_count: int
    approved: bool
    tool_log: list[ToolCallRecord] = field(default_factory=list)
    trace_url: Optional[str] = None


def extract_tool_log(messages: list[BaseMessage]) -> list[ToolCallRecord]:
    """Derive a ToolCallRecord list from a drafter conversation.

    Walks the message list once: every AIMessage.tool_calls entry is matched to
    its ToolMessage by tool_call_id. The messages list is the single source of
    truth; this is a read-only projection.
    """
    logger.debug("extract_tool_log: scanning {} messages", len(messages))
    pending: dict[str, tuple[str, dict]] = {}
    records: list[ToolCallRecord] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                pending[tc["id"]] = (tc["name"], tc.get("args", {}))
        if isinstance(msg, ToolMessage):
            name, args = pending.get(msg.tool_call_id, (msg.name or "unknown", {}))
            success = getattr(msg, "status", "success") != "error"
            content = str(msg.content)
            records.append(ToolCallRecord(
                name=name,
                args=args,
                result=content[:_RESULT_TRUNCATE],
                success=success,
                error=None if success else content,
            ))
    logger.info("extract_tool_log: derived {} tool-call records", len(records))
    return records
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/core/test_report_state.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add report state types and extract_tool_log helper"
```

---

## Task 3: Data tools — `report/tools.py`

`make_report_tools(db_path)` returns 7 LangChain `@tool` wrappers around `db/queries.py`. Three trend granularities are three separate tools — the LLM picks which to call.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/core/test_report_tools.py`:

```python
"""Tests for spotify_core.report.tools — the drafter's data tools."""
from spotify_core.db.migrations import get_connection, init_history_db
from spotify_core.report.tools import make_report_tools


def _seed(db_path, rows):
    """Insert minimal listening_history rows for tool tests."""
    conn = get_connection(db_path)
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'json_import')",
                (
                    r["id"], r.get("track_id", r["id"]),
                    r.get("track_name", "T"), r.get("artist_name", "A"),
                    r["played_at"], r["ms_played"],
                ),
            )
    conn.close()


def _tools(db_path):
    return {t.name: t for t in make_report_tools(db_path)}


def test_make_report_tools_names(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    assert set(_tools(db)) == {
        "get_listening_summary", "get_top_artists", "get_top_tracks",
        "get_daily_activity_pattern", "get_daily_trend", "get_weekly_trend",
        "get_monthly_trend",
    }


def test_top_artists_tool_returns_rows(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 200_000,
         "artist_name": "Radiohead"},
        {"id": "2", "played_at": "2024-01-09T09:00:00Z", "ms_played": 100_000,
         "artist_name": "Radiohead"},
    ])
    rows = _tools(db)["get_top_artists"].invoke(
        {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert rows[0]["artist_name"] == "Radiohead"
    assert rows[0]["total_ms"] == 300_000


def test_trend_tools_return_expected_keys(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-03-08T09:00:00Z", "ms_played": 90_000},
    ])
    tools = _tools(db)
    rng = {"start_date": "2024-01-01", "end_date": "2024-12-31"}
    assert all("date" in r for r in tools["get_daily_trend"].invoke(rng))
    assert all("week_label" in r for r in tools["get_weekly_trend"].invoke(rng))
    assert all("month_label" in r for r in tools["get_monthly_trend"].invoke(rng))


def test_summary_tool_date_passthrough(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-03-08T09:00:00Z", "ms_played": 60_000},
    ])
    summary = _tools(db)["get_listening_summary"].invoke(
        {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert summary["total_plays"] == 1
```

- [ ] **Step 2: Implement `tools.py`**

Create `packages/core/spotify_core/report/tools.py`:

```python
"""LangChain @tool wrappers around db/queries.py for the report drafter.

make_report_tools(db_path) binds db_path via closure; the LLM only supplies the
start_date / end_date arguments. Each tool's docstring is its LLM-facing
description. The three trend granularities are three separate tools — the LLM
chooses which to call, guided by their docstrings.
"""
from loguru import logger
from langchain_core.tools import BaseTool, tool

from ..db import queries


def make_report_tools(db_path: str) -> list[BaseTool]:
    """Build the drafter's data tools, each bound to db_path via closure."""
    logger.debug("make_report_tools: db_path={}", db_path)

    @tool
    def get_listening_summary(start_date: str, end_date: str) -> dict:
        """Overall listening stats for the date range: total plays, listening
        time, unique tracks/artists, skip rate. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_listening_summary(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_top_artists(start_date: str, end_date: str) -> list[dict]:
        """The 10 most-listened artists for the date range, by listening time.
        Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_top_artists(
            db_path, limit=10, start_date=start_date, end_date=end_date
        )

    @tool
    def get_top_tracks(start_date: str, end_date: str) -> list[dict]:
        """The 10 most-played tracks for the date range, by play count.
        Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_top_tracks(
            db_path, limit=10, start_date=start_date, end_date=end_date
        )

    @tool
    def get_daily_activity_pattern(start_date: str, end_date: str) -> list[dict]:
        """Listening volume per weekday and per time-of-day segment (0-6, 7-12,
        13-18, 19-23) for the date range. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_daily_activity_pattern(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_daily_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-calendar-day listening totals for the date range. Best for short
        ranges of up to about two weeks. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_daily_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_weekly_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-week listening totals for the date range. Best for medium ranges
        of roughly one to three months. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_weekly_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_monthly_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-month listening totals for the date range. Best for long ranges
        of several months or more. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_monthly_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    tools: list[BaseTool] = [
        get_listening_summary,
        get_top_artists,
        get_top_tracks,
        get_daily_activity_pattern,
        get_daily_trend,
        get_weekly_trend,
        get_monthly_trend,
    ]
    logger.info("make_report_tools: built {} tools", len(tools))
    return tools
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/core/test_report_tools.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add report data tools wrapping db/queries"
```

---

## Task 4: Provider factory — `report/models.py`

`build_chat_model(provider, model)` dispatches on a provider name. Google is implemented; OpenAI/Anthropic are skeletons. `_GOOGLE_API_KEY` is resolved once at module import.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/core/test_report_models.py`:

```python
"""Tests for spotify_core.report.models.build_chat_model.

_GOOGLE_API_KEY is resolved at module import, so the tests patch the module
attribute directly (monkeypatch.setattr) rather than the environment.
"""
import pytest

from spotify_core.report import models
from spotify_core.report.models import build_chat_model


def test_google_returns_chat_model(monkeypatch):
    monkeypatch.setattr(models, "_GOOGLE_API_KEY", "fake-key")
    chat = build_chat_model("google", "gemini-2.5-flash")
    from langchain_google_genai import ChatGoogleGenerativeAI
    assert isinstance(chat, ChatGoogleGenerativeAI)


def test_google_missing_key_raises(monkeypatch):
    monkeypatch.setattr(models, "_GOOGLE_API_KEY", None)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_chat_model("google", "gemini-2.5-flash")


def test_openai_skeleton_raises():
    with pytest.raises(NotImplementedError):
        build_chat_model("openai", "gpt-4o")


def test_anthropic_skeleton_raises():
    with pytest.raises(NotImplementedError):
        build_chat_model("anthropic", "claude-sonnet-4-6")


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_chat_model("groq", "whatever")
```

- [ ] **Step 2: Implement `models.py`**

Create `packages/core/spotify_core/report/models.py`:

```python
"""LLM provider factory for the report graph.

build_chat_model dispatches on a provider name and returns a LangChain
BaseChatModel. Google is the only implemented provider in v1; OpenAI and
Anthropic are skeletons with a final signature so enabling them later is a
localized change.
"""
import os

from loguru import logger
from langchain_core.language_models import BaseChatModel

from ..env import ensure_dotenv_loaded

# Resolve the provider key once, at import — after the platform .env is loaded.
# Kept at module scope (not inside build_chat_model) so a future config source
# other than .env can be swapped in here without touching the factory.
ensure_dotenv_loaded()
_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


def build_chat_model(provider: str, model: str) -> BaseChatModel:
    """Return a chat model for the given provider.

    Args:
        provider: One of "google", "openai", "anthropic".
        model: Provider-specific model name, e.g. "gemini-2.5-flash".

    Raises:
        ValueError: Unknown provider, or the provider's API key is missing.
        NotImplementedError: provider is "openai" or "anthropic" (v1 skeletons).
    """
    logger.debug("build_chat_model: provider={} model={}", provider, model)
    if provider == "google":
        if not _GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY is not set. Add it to your .env to use the "
                "AI report block."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        logger.info("build_chat_model: ChatGoogleGenerativeAI model={}", model)
        return ChatGoogleGenerativeAI(
            model=model, temperature=0.7, google_api_key=_GOOGLE_API_KEY
        )
    if provider == "openai":
        # TODO: implement the OpenAI provider branch (ChatOpenAI).
        raise NotImplementedError("OpenAI provider is not implemented yet.")
    if provider == "anthropic":
        # TODO: implement the Anthropic provider branch (ChatAnthropic).
        raise NotImplementedError("Anthropic provider is not implemented yet.")
    raise ValueError(f"Unknown LLM provider: {provider!r}")
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/core/test_report_models.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add LLM provider factory for the report graph"
```

---

## Task 5: Prompts and observability — `report/prompts.py`, `report/observability.py`

Style templates + reviewer rubric, and optional Langfuse helpers that degrade silently when keys are absent.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/core/test_report_observability.py`:

```python
"""Tests for spotify_core.report.observability and prompts."""
from spotify_core.report.observability import get_langfuse_callbacks, get_trace_url
from spotify_core.report.prompts import REVIEWER_RUBRIC, STYLE_TEMPLATES


def test_langfuse_callbacks_empty_without_keys(monkeypatch):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert get_langfuse_callbacks() == []


def test_get_trace_url_none_without_callbacks():
    assert get_trace_url([]) is None


def test_style_templates_include_required_styles():
    # monthly_review and roast are the must-have styles; the set may grow or
    # shrink, so this asserts a subset rather than an exact match.
    assert {"monthly_review", "roast"} <= set(STYLE_TEMPLATES)
    assert all(v.strip() for v in STYLE_TEMPLATES.values())


def test_reviewer_rubric_describes_output_fields():
    assert REVIEWER_RUBRIC.strip()
    assert "approved" in REVIEWER_RUBRIC
    assert "feedback" in REVIEWER_RUBRIC
```

- [ ] **Step 2: Implement `prompts.py`**

Create `packages/core/spotify_core/report/prompts.py`:

```python
"""Prompt templates for the report graph.

STYLE_TEMPLATES maps a style key to the drafter's system prompt. REVIEWER_RUBRIC
is the reviewer's system prompt. All four styles must produce a grounded,
opinionated piece in Traditional Chinese.
"""

_SHARED_DRAFTER_RULES = """\
你正在為使用者撰寫一篇個人聽歌分析文章。

規則：
- 你只能依據工具回傳的實際資料寫作，嚴禁編造數字、歌曲或藝人。
- 先呼叫需要的資料工具（可多次呼叫），取得足夠資料後再寫出完整文章。
- 文章用繁體中文，使用 Markdown，包含標題與分段。
- 文章要有明確觀點，不要只是流水帳般地列數據。
"""

_MONTHLY_REVIEW = _SHARED_DRAFTER_RULES + """
風格：月度回顧。語氣平衡、誠懇，像一篇用心的月報。
聚焦聽歌習慣的變化、最投入的藝人與歌曲、活躍時段，並給出有依據的小結。
"""

_ROAST = _SHARED_DRAFTER_RULES + """
風格：毒舌吐槽。語氣辛辣、好笑、毫不留情地吐槽使用者的品味，
但所有吐槽都必須建立在真實資料上。可以誇張，但不可造假。
"""

_GENTLE = _SHARED_DRAFTER_RULES + """
風格：溫和鼓勵。語氣親切、正向，像朋友般肯定使用者的聽歌選擇，
溫柔地點出有趣的觀察。
"""

_CRITIC = _SHARED_DRAFTER_RULES + """
風格：專業樂評。語氣理性、有洞見，像專業樂評人分析使用者的聆聽輪廓，
討論曲風傾向與聆聽行為，並提出有見地的評論。
"""

STYLE_TEMPLATES: dict[str, str] = {
    "monthly_review": _MONTHLY_REVIEW,
    "roast": _ROAST,
    "gentle": _GENTLE,
    "critic": _CRITIC,
}

REVIEWER_RUBRIC = """\
你是這篇聽歌分析文章的編輯。請依下列標準審查草稿：

1. 紮實度：文章引用的數據、藝人、歌曲，必須出現在提供的工具呼叫紀錄中。
   若有任何無法對應到資料的內容，視為不合格。
2. 觀點：文章必須有明確觀點，不能只是條列數據。
3. 風格：文章必須符合指定風格（毒舌要夠辛辣好笑、月度回顧要平衡、
   溫和要正向、專業樂評要有洞見）。

請以 JSON 物件回應，包含且僅包含兩個欄位：
- "approved"：布林值。三項標準全部通過時為 true，否則為 false。
- "feedback"：字串。approved 為 false 時，寫出具體、可執行的修改建議；
  approved 為 true 時為空字串。
"""
```

- [ ] **Step 3: Implement `observability.py`**

Create `packages/core/spotify_core/report/observability.py`:

```python
"""Optional Langfuse tracing for the report graph.

get_langfuse_callbacks returns a LangChain callback list when all three
Langfuse env vars are present, and an empty list otherwise. get_trace_url is a
best-effort lookup of a finished run's trace URL. Both degrade silently when
Langfuse is not configured — the graph always runs.
"""
import os
from typing import Optional

from loguru import logger

_LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def _langfuse_configured() -> bool:
    return all(os.getenv(k) for k in _LANGFUSE_KEYS)


def get_langfuse_callbacks() -> list:
    """Return [CallbackHandler()] if Langfuse is fully configured, else []."""
    if not _langfuse_configured():
        logger.debug("get_langfuse_callbacks: Langfuse keys absent — tracing off")
        return []
    try:
        from langfuse.langchain import CallbackHandler
        logger.info("get_langfuse_callbacks: Langfuse tracing enabled")
        return [CallbackHandler()]
    except Exception:
        logger.exception("get_langfuse_callbacks: failed to init Langfuse")
        return []


def get_trace_url(callbacks: list) -> Optional[str]:
    """Best-effort: the Langfuse trace URL for the run that used these callbacks.

    Returns None when Langfuse is not configured, or whenever the trace id /
    URL cannot be resolved — tracing is optional and must never break a run.

    Args:
        callbacks: The list returned by get_langfuse_callbacks and threaded
            through the just-completed graph run.
    """
    if not callbacks:
        return None
    handler = callbacks[0]
    try:
        # The v3 CallbackHandler exposes the last run's trace id; the attribute
        # name has shifted across releases, so try both known forms.
        trace_id = getattr(handler, "last_trace_id", None)
        if trace_id is None and hasattr(handler, "get_trace_id"):
            trace_id = handler.get_trace_id()
        if not trace_id:
            logger.debug("get_trace_url: no trace id on the callback handler")
            return None
        from langfuse import get_client
        url = get_client().get_trace_url(trace_id=trace_id)
        logger.info("get_trace_url: resolved trace URL")
        return url
    except Exception:
        logger.exception("get_trace_url: failed to resolve trace URL")
        return None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/core/test_report_observability.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add report prompts and Langfuse observability"
```

---

## Task 6: The graph — `report/nodes.py`, `report/graph.py`

2-node LangGraph (drafter + reviewer + conditional edge) and `generate_report` entry point. Tested with a scripted fake chat model — no API calls.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/core/test_report_graph.py`:

```python
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
            AIMessage(content="# 月度回顧\n你聽了 A。"),
        ],
        review_verdicts=[ReviewVerdict(approved=True, feedback="")],
    )
    result = generate_report(
        style="monthly_review", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    assert result.approved is True
    assert result.revision_count == 0
    assert result.text == "# 月度回顧\n你聽了 A。"
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
        style="critic", start_date="2024-01-01", end_date="2024-01-31",
        db_path=db, model=model,
    )
    # Cap is 2 rejections: 1 initial draft + 1 revision, then a forced end.
    assert result.approved is False
    assert result.revision_count == 2
    assert result.text == "草稿二"
```

- [ ] **Step 2: Implement `nodes.py`**

Create `packages/core/spotify_core/report/nodes.py`:

```python
"""Graph nodes for the report graph: drafter, reviewer, route_after_review.

make_report_nodes(tools) returns the three callables bound to the tool list via
closure — the same factory pattern used by spotify_core/agent/nodes.py.
"""
from loguru import logger
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from .prompts import REVIEWER_RUBRIC, STYLE_TEMPLATES
from .state import ReportState, ReviewVerdict, extract_tool_log

# Hard caps that guarantee the graph terminates.
_MAX_TOOL_ITERATIONS = 10
_MAX_REVISIONS = 2


def make_report_nodes(tools: list):
    """Return (drafter_node, reviewer_node, route_after_review) bound to tools."""
    tools_by_name = {t.name: t for t in tools}

    def drafter_node(state: ReportState, config: RunnableConfig) -> dict:
        """Write (or revise) the report, calling data tools in a bounded loop."""
        logger.info("drafter_node: style={} revision={}",
                    state["style"], state["revision_count"])
        model = config["configurable"]["model"]
        model_with_tools = model.bind_tools(tools)

        system = STYLE_TEMPLATES[state["style"]]
        user = (
            f"請分析使用者從 {state['start_date']} 到 {state['end_date']} "
            f"的聽歌資料，並寫出文章。"
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        if state["review_feedback"]:
            messages.append(HumanMessage(content=(
                f"你上一版的草稿：\n{state['draft']}\n\n"
                f"編輯的修改意見，請據此改寫：\n{state['review_feedback']}"
            )))

        draft = ""
        for i in range(_MAX_TOOL_ITERATIONS):
            response = model_with_tools.invoke(messages, config=config)
            messages.append(response)
            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                draft = response.content
                break
            logger.debug("drafter_node: iteration {}, {} tool call(s)",
                         i, len(tool_calls))
            for tool_call in tool_calls:
                report_tool = tools_by_name.get(tool_call["name"])
                if report_tool is None:
                    logger.warning("drafter_node: unknown tool {}",
                                   tool_call["name"])
                    messages.append(ToolMessage(
                        content=f"Unknown tool: {tool_call['name']}",
                        tool_call_id=tool_call["id"],
                        status="error",
                    ))
                    continue
                messages.append(report_tool.invoke(tool_call, config=config))
        else:
            logger.warning("drafter_node: hit tool-iteration cap")
            last = messages[-1]
            draft = getattr(last, "content", "") or state["draft"]

        tool_log = extract_tool_log(messages)
        logger.info("drafter_node: draft {} chars, {} tool calls",
                    len(draft), len(tool_log))
        return {"draft": draft, "tool_log": tool_log}

    def reviewer_node(state: ReportState, config: RunnableConfig) -> dict:
        """Judge the draft; approve or return revision feedback."""
        logger.info("reviewer_node: reviewing revision {}",
                    state["revision_count"])
        model = config["configurable"]["model"]
        reviewer = model.with_structured_output(ReviewVerdict)

        tool_summary = "\n".join(
            f"- {r.name}({r.args}) -> {'OK' if r.success else 'ERROR'}: {r.result}"
            for r in state["tool_log"]
        ) or "（沒有工具呼叫紀錄）"
        messages = [
            SystemMessage(content=REVIEWER_RUBRIC),
            HumanMessage(content=(
                f"指定風格：{state['style']}\n\n"
                f"草稿：\n{state['draft']}\n\n"
                f"草稿作者實際取得的資料：\n{tool_summary}"
            )),
        ]
        verdict: ReviewVerdict = reviewer.invoke(messages, config=config)
        if verdict.approved:
            logger.info("reviewer_node: approved")
            return {
                "approved": True,
                "review_feedback": "",
                "final_report": state["draft"],
            }
        logger.info("reviewer_node: rejected — {}", verdict.feedback[:120])
        return {
            "approved": False,
            "review_feedback": verdict.feedback,
            "revision_count": state["revision_count"] + 1,
            "final_report": state["draft"],
        }

    def route_after_review(state: ReportState) -> str:
        """Approved or revision cap reached -> end; otherwise revise."""
        if state["approved"] or state["revision_count"] >= _MAX_REVISIONS:
            logger.info("route_after_review: end (approved={}, revisions={})",
                        state["approved"], state["revision_count"])
            return "end"
        logger.info("route_after_review: back to drafter")
        return "drafter"

    return drafter_node, reviewer_node, route_after_review
```

- [ ] **Step 3: Implement `graph.py`**

Create `packages/core/spotify_core/report/graph.py`:

```python
"""The report LangGraph (drafter -> reviewer -> revise|end) and the
generate_report orchestration entry point the UI calls."""
from loguru import logger
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from .nodes import make_report_nodes
from .observability import get_langfuse_callbacks, get_trace_url
from .state import ReportResult, ReportState
from .tools import make_report_tools


def build_report_graph(tools: list):
    """Construct and compile the 2-node report StateGraph."""
    drafter_node, reviewer_node, route_after_review = make_report_nodes(tools)
    graph = StateGraph(ReportState)
    graph.add_node("drafter", drafter_node)
    graph.add_node("reviewer", reviewer_node)
    graph.set_entry_point("drafter")
    graph.add_edge("drafter", "reviewer")
    graph.add_conditional_edges(
        "reviewer", route_after_review, {"drafter": "drafter", "end": END}
    )
    logger.debug("build_report_graph: compiled report graph")
    return graph.compile()


def generate_report(
    *,
    style: str,
    start_date: str,
    end_date: str,
    db_path: str,
    model: BaseChatModel,
) -> ReportResult:
    """Run the report graph end-to-end and return a UI-friendly result.

    Args:
        style: One of "monthly_review", "roast", "gentle", "critic".
        start_date: ISO "YYYY-MM-DD" range start.
        end_date: ISO "YYYY-MM-DD" range end.
        db_path: Path to history.db.
        model: The chat model used by both the drafter and the reviewer.
    """
    logger.info("generate_report: style={} range={}..{}",
                style, start_date, end_date)
    tools = make_report_tools(db_path)
    graph = build_report_graph(tools)
    callbacks = get_langfuse_callbacks()
    config = {
        "configurable": {"model": model},
        "callbacks": callbacks,
    }
    initial: ReportState = {
        "style": style,
        "start_date": start_date,
        "end_date": end_date,
        "draft": "",
        "review_feedback": "",
        "revision_count": 0,
        "approved": False,
        "tool_log": [],
        "final_report": "",
    }
    final = graph.invoke(initial, config=config)
    trace_url = get_trace_url(callbacks)
    result = ReportResult(
        text=final["final_report"] or final["draft"],
        style=style,
        revision_count=final["revision_count"],
        approved=final["approved"],
        tool_log=final["tool_log"],
        trace_url=trace_url,
    )
    logger.info("generate_report: done — approved={} revisions={}",
                result.approved, result.revision_count)
    return result
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/core/test_report_graph.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add report graph nodes and generate_report orchestration"
```

---

## Task 7: Web integration — `get_llm_config`, `ai_block.py`, dashboard wiring

Adds the LLM-choice config helper, the Streamlit AI section, wires it into the dashboard, and runs the full suite. Streamlit rendering is verified manually.

_(TDD: verify tests fail before implementing, pass after.)_

- [ ] **Step 1: Write the test**

Create `tests/web/test_web_config.py`:

```python
"""Tests for spotify_web.config.get_llm_config."""
from spotify_web.config import get_llm_config


def test_get_llm_config_lists_google_models_when_key_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    config = get_llm_config()
    assert config["models"]
    assert all(m["provider"] == "google" for m in config["models"])
    assert config["default"] == config["models"][0]


def test_get_llm_config_empty_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    config = get_llm_config()
    assert config["models"] == []
    assert config["default"] is None
```

- [ ] **Step 2: Add `get_llm_config` to `spotify_web/config.py`**

Overwrite `apps/web/spotify_web/config.py` with:

```python
"""Config helpers for the dashboard: sync credentials and LLM provider choices.

SPOTIFY_CLIENT_ID and TOKEN_ENCRYPT_KEY are read from the environment (after
loading the platformdirs .env); DB paths and user id come from settings.
"""
import os

from spotify_core.env import ensure_dotenv_loaded, get_client_id, get_fernet_key

ensure_dotenv_loaded()
from spotify_core.config import settings

# LLM models offered by the AI report block, per provider. v1 ships Google only.
_GOOGLE_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]


def get_sync_args() -> dict:
    """Return the keyword arguments for spotify_core.db.pipeline.sync_api_to_db."""
    return {
        "db_path": str(settings.history_db_path),
        "tokens_db_path": str(settings.tokens_db_path),
        "user_id": settings.spotify_user_id,
        "client_id": get_client_id(),
        "fernet_key": get_fernet_key(),
    }


def get_llm_config() -> dict:
    """Return the LLM choices available to the AI report block.

    Inspects the environment for provider API keys. In v1 only GOOGLE_API_KEY
    yields usable models.

    Returns:
        {"models": [{"provider": str, "model": str}, ...],
         "default": {"provider": str, "model": str} | None}
    """
    models: list[dict] = []
    if os.getenv("GOOGLE_API_KEY"):
        models = [{"provider": "google", "model": m} for m in _GOOGLE_MODELS]
    return {"models": models, "default": models[0] if models else None}
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/web/test_web_config.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 4: Create `ai_block.py`**

Create `apps/web/ui/ai_block.py`:

```python
"""AI 聽歌分析 — report-generation section of the dashboard (Streamlit)."""
import datetime

import streamlit as st
from loguru import logger

from spotify_core.config import settings
from spotify_core.db.queries import is_history_empty
from spotify_core.report.graph import generate_report
from spotify_core.report.models import build_chat_model

from spotify_web.config import get_llm_config

_DB_PATH = str(settings.history_db_path)

# Style key -> UI label.
_STYLES = {
    "monthly_review": "📅 月度回顧",
    "roast": "🔥 毒舌",
    "gentle": "😊 溫和",
    "critic": "🎼 專業樂評",
}


def _render_report(result, model_label: str) -> None:
    """Render a finished ReportResult: the article plus a status caption."""
    st.markdown(result.text)
    tools_used = ", ".join(sorted({r.name for r in result.tool_log})) or "（無）"
    status = "✅ 已通過審查" if result.approved else "⚠️ 已達修訂上限"
    st.caption(
        f"{status}｜模型：{model_label}｜修訂次數：{result.revision_count}｜"
        f"使用工具：{tools_used}"
    )
    if result.trace_url:
        st.caption(f"[在 Langfuse 查看追蹤]({result.trace_url})")


def render_ai_block(default_start: str, default_end: str) -> None:
    """Render the AI report section below the dashboard.

    Args:
        default_start: ISO date the date pickers default to (dashboard period).
        default_end: ISO date the date pickers default to.
    """
    st.divider()
    st.subheader("🤖 AI 聽歌分析")

    if is_history_empty(_DB_PATH):
        st.info("資料庫沒有播放紀錄，無法產生分析。")
        return

    llm_config = get_llm_config()
    if not llm_config["models"]:
        st.info(
            "尚未設定 LLM 金鑰。請在 .env 加入 `GOOGLE_API_KEY` 後重新啟動，"
            "即可使用 AI 分析。"
        )
        return

    col_style, col_model = st.columns(2)
    with col_style:
        style = st.selectbox(
            "分析風格",
            options=list(_STYLES),
            format_func=lambda k: _STYLES[k],
            key="ai_style",
        )
    with col_model:
        model_choice = st.selectbox(
            "模型",
            options=llm_config["models"],
            format_func=lambda m: f"{m['provider']} / {m['model']}",
            key="ai_model",
        )

    col_start, col_end = st.columns(2)
    start = col_start.date_input(
        "開始", value=datetime.date.fromisoformat(default_start), key="ai_start"
    )
    end = col_end.date_input(
        "結束", value=datetime.date.fromisoformat(default_end), key="ai_end"
    )

    if st.button("✨ 產生分析", key="ai_generate"):
        try:
            with st.spinner("AI 正在分析你的聽歌資料…"):
                model = build_chat_model(
                    model_choice["provider"], model_choice["model"]
                )
                result = generate_report(
                    style=style,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    db_path=_DB_PATH,
                    model=model,
                )
            st.session_state["ai_report"] = result
            st.session_state["ai_report_model"] = (
                f"{model_choice['provider']} / {model_choice['model']}"
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            logger.exception("AI report generation failed")
            st.error(f"產生分析時發生錯誤：{exc}")

    if "ai_report" in st.session_state:
        _render_report(
            st.session_state["ai_report"],
            st.session_state.get("ai_report_model", ""),
        )
```

- [ ] **Step 5: Wire `render_ai_block` into the dashboard**

In `apps/web/ui/dashboard.py`, replace:

```python
from spotify_web.charts import daily_activity_figure, trend_figure
from spotify_web.config import get_sync_args
from spotify_web.formatting import format_duration_ms, spotify_uri_to_url
```

with:

```python
from spotify_web.charts import daily_activity_figure, trend_figure
from spotify_web.config import get_sync_args
from spotify_web.formatting import format_duration_ms, spotify_uri_to_url

from ai_block import render_ai_block
```

At the very end of `render_dashboard()`, replace:

```python
    st.divider()
    _recent_section()
```

with:

```python
    st.divider()
    _recent_section()

    render_ai_block(start, end)
```

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest -q
```

Expected: PASS — all `tests/core/test_report_*.py` and `tests/web/test_web_config.py`. Note any pre-existing unrelated failures; do not fix them here.

- [ ] **Step 7: Manual smoke-test the AI block**

Set `GOOGLE_API_KEY` in your platform `.env` (`uv run python -c "from spotify_core import paths; print(paths.env_file())"` prints its path).

Run: `uv run streamlit run apps/web/ui/main_page.py --server.headless true`

Open the URL, scroll to the bottom of the Dashboard. Confirm:
- The "🤖 AI 聽歌分析" section appears below "Recently Played".
- Style and model dropdowns render; date inputs default to the dashboard period.
- Clicking "✨ 產生分析" shows a spinner, then renders a Markdown article and a status caption.
- If Langfuse keys are set, a "在 Langfuse 查看追蹤" link appears.
- Temporarily unset `GOOGLE_API_KEY` and restart — confirm the "尚未設定 LLM 金鑰" notice appears.

Stop the server with Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git commit -m "feat: add AI report block to the dashboard"
```
