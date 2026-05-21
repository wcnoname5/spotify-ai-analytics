# AI Report Block — Design

**Date:** 2026-05-21
**Owner:** wcnoname5
**Relates to:** `2026-05-21-local-dashboard-design.md` (adds an AI section to the
dashboard built there).

---

## 1. Goal

Add an **AI section** to the bottom of the dashboard
([`apps/web/ui/dashboard.py`](../../../apps/web/ui/dashboard.py)) with three
user-facing features:

1. **Monthly listening review** — an LLM generates an opinionated analytical
   article from the user's listening data for a chosen time range.
2. **"Roast My Taste"** — the same engine with a selectable tone (savage /
   gentle / pro-critic), generating a taste analysis.
3. **Period playlist** — a playlist of the user's top tracks for the selected
   period is built (rule-based, from `history.db`) and created in the user's
   real Spotify account.

The report engine is a deliberately minimal **LangGraph** graph (2 nodes, 1
conditional edge: a drafter and a reviewer). Every run is traced with
**Langfuse**. LLM providers are swappable via the LangChain `BaseChatModel`
abstraction so later model comparisons (GPT-4o vs Claude vs Gemini) need no
graph changes.

### Non-goals

- **No desktop packaging.** `pywebview` / `PyInstaller` is a separate follow-up
  spec; this work ships on the existing `.bat` + `uv run streamlit` launcher.
- **No web search.** The drafter is grounded purely in the local DB. The graph
  leaves room to add a search tool later.
- **No new tracks from outside the user's history.** Spotify deprecated its
  `/recommendations` endpoint (Nov 2024); the period playlist is built
  rule-based from tracks already in `history.db`.
- **No report persistence.** Reports are ephemeral (per Streamlit session).
  Langfuse retains the run history; no schema change.
- **No change to `packages/core/spotify_core/agent/`.** That 3-node graph stays
  for the later Chainlit chatbot; this is a brand-new, separate graph.
- **No custom user-authored tone prompts.** Exactly four fixed styles.

---

## 2. Key decisions (resolved during brainstorming)

| Decision | Choice |
|---|---|
| Spec scope | AI block only; desktop packaging and app/wizard decoupling deferred to their own specs |
| Drafter data access | In-process LangChain `@tool` wrappers around `queries.py` — no MCP transport |
| Playlist | Rule-based selection from the user's own history (`history.db`) — no LLM |
| Web search | Excluded from v1 |
| Model selection | Provider keys via an in-app web settings panel; a Streamlit dropdown picks the model |
| Provider rollout | Google implemented first; OpenAI/Anthropic left as `# TODO` skeletons |
| Langfuse | Optional — traces when keys are present, silent no-op when absent |
| Report storage | Ephemeral — regenerated on demand, not persisted |
| Graph structure | Approach A — drafter node owns an internal bounded tool loop |

---

## 3. Architecture overview

`apps/web` and `apps/mcp` are independent apps over a shared `spotify_core`.
They are **not fully decoupled today** — the dashboard's `.bat` launcher shells
out to the `spotify-mcp` CLI for OAuth / history setup. Fully decoupling them
(extracting the shared setup wizard into `spotify_core` so each app installs and
sets up on its own) is a follow-up spec (see §13). This spec deliberately keeps
the **AI feature's** setup self-contained inside `apps/web` — the in-app
settings panel (§10.2) — so it introduces no new `apps/mcp` coupling.

```text
apps/web/ui/dashboard.py
        └── render_ai_block()  ──────────────────┐
apps/web/ui/ai_block.py  (new, Streamlit)         │
        ├── generate_report(...)                  │  packages/core/spotify_core/report/
        └── build_playlist_proposal(...) + confirm ┘
                                                  ▼
packages/core/spotify_core/report/   (no Streamlit — unit-testable)
        graph.py        build_report_graph(tools) + generate_report(...)
        nodes.py        drafter_node, reviewer_node, route_after_review
        state.py        ReportState, ToolCallRecord, extract_tool_log
        tools.py        make_report_tools(db_path) -> list[BaseTool]
        prompts.py      4 drafter style templates + reviewer rubric
        models.py       build_chat_model(provider, model) -> BaseChatModel  (Google first)
        playlist.py     build_playlist_proposal(...) -> PlaylistProposal  (rule-based)
        observability.py get_langfuse_callbacks() -> list
```

Layering follows the existing rules in `CLAUDE.md`:

- `packages/core/spotify_core/report/` imports only from `packages/core` and
  LangChain/LangGraph/Langfuse libraries. No Streamlit, no `apps/*` imports.
- `apps/web` imports from `packages/core` only.

---

## 4. The graph — `report/graph.py`, `report/nodes.py`, `report/state.py`

A minimal LangGraph workflow: **2 nodes, 1 conditional edge.**

```
START → drafter → reviewer → route_after_review → drafter (revise)
                                               └→ END
```

### 4.1 State — `ReportState` (TypedDict)

| Field | Type | Purpose |
|---|---|---|
| `style` | `str` | One of `monthly_review`, `roast`, `gentle`, `critic` |
| `start_date` | `str` | ISO `YYYY-MM-DD` |
| `end_date` | `str` | ISO `YYYY-MM-DD` |
| `draft` | `str` | Latest drafter output |
| `review_feedback` | `str` | Reviewer's notes from the last rejection (`""` initially) |
| `revision_count` | `int` | Number of completed reviewer rejections (starts `0`) |
| `approved` | `bool` | Set by the reviewer |
| `tool_log` | `list[ToolCallRecord]` | Every tool call the drafter made, across all passes |
| `final_report` | `str` | The text returned to the UI |

`ToolCallRecord` is a small dataclass / TypedDict: `{name: str, args: dict,
result: str, success: bool, error: str | None}`. It is a **derived projection**
of the native `AIMessage.tool_calls` + `ToolMessage` pairs — not a parallel
record maintained during the loop. A helper `extract_tool_log(messages) ->
list[ToolCallRecord]` walks the message list once at the end of each drafter
pass and builds the log from the authoritative source. This eliminates drift
risk: the `messages` list is the single source of truth; `tool_log` is derived.

The `result` field carries a truncated summary of the tool's return value (from
`ToolMessage.content`), so the reviewer can verify the draft is grounded in the
actual data the drafter fetched — not just that a tool was called.

Consumers: the reviewer (grounding check), the UI caption (§9), and tests (§12).

### 4.2 `drafter_node`

Signature: `drafter_node(state: ReportState, config: RunnableConfig)` — LangGraph
passes `config`, which carries the Langfuse callback (§7).

- Reads the chat model from `config["configurable"]["model"]` (see §6) and binds
  the report tools (`make_report_tools(db_path)`).
- Builds the prompt: the style's system template (`prompts.py`) + a user message
  stating the date range. On a revision pass (`review_feedback != ""`), the prior
  `draft` and the feedback are appended so the model knows what to fix.
- Runs a **bounded internal tool loop** (max 10 iterations) over a `messages`
  list:
  1. `model_with_tools.invoke(messages, config=config)`.
  2. If the response has `tool_calls` → append the `AIMessage` (it carries the
     tool name + args), execute each tool via `tool.invoke(tool_call,
     config=config)`, append the resulting `ToolMessage` (carries the result and
     a `status` of `"success"`/`"error"`). Repeat.
  3. If no `tool_calls` → the response content is the draft; exit the loop.
  If the loop hits the iteration cap, the last response content is used as the
  draft.
- **Tool-call visibility (Goal 1)**: the `messages` list is the running
  conversation — every prior `AIMessage`/`ToolMessage` pair stays in it, so each
  `model.invoke` sees all prior tool names, args, results, and statuses. This is
  the native LangChain mechanism; no custom record is needed for the LLM.
- **Tracing (Goal 2)**: because `config` is threaded into every `model.invoke` /
  `tool.invoke`, Langfuse's `CallbackHandler` auto-emits one generation span per
  LLM call and one span per tool execution, **nested under the `drafter` node**.
  A run reads as `graph → drafter → [gen, tool, gen, tool, gen] → reviewer`.
  Each tool call is individually observable in the outer Langfuse trace.
- **Deriving `tool_log`**: after the loop exits, calls
  `extract_tool_log(messages)` to build `tool_log` from the `AIMessage` /
  `ToolMessage` pairs accumulated during the loop. This is a one-time projection
  — the loop itself never touches `tool_log`.
- Writes `draft` and the derived `tool_log`.

### 4.3 `reviewer_node`

- Uses the same chat model with **structured output** → `ReviewVerdict`
  (`approved: bool`, `feedback: str`).
- The rubric is style-aware (see `prompts.py`): a `roast` draft must actually be
  savage and funny; `monthly_review` must stay balanced and evidence-backed;
  every style must be grounded in the data and have a clear viewpoint. The
  reviewer also sees `tool_log` (including truncated `result` summaries) so it
  can check the draft only cites data the drafter actually fetched — not just
  that a tool was called, but what it returned.
- On **approve**: sets `approved = True`.
- On **reject**: sets `approved = False`, writes `feedback` to `review_feedback`,
  increments `revision_count`.

### 4.4 `route_after_review` (conditional edge)

- `approved is True` **or** `revision_count >= 2` → set `final_report = draft`,
  go to `END`.
- Otherwise → back to `drafter`.

The `revision_count >= 2` hard cap guarantees termination: at most 1 initial
draft + 2 revisions = 3 drafter passes.

### 4.5 `generate_report(...)` orchestration

This is a **thin orchestration wrapper** — the single entry point the UI calls,
so the UI never imports LangGraph directly. It does not contain logic; it wires
the graph, invokes it, and maps the final state to a UI-friendly result.

```python
def generate_report(
    *, style: str, start_date: str, end_date: str,
    db_path: str, model: BaseChatModel,
) -> ReportResult: ...
```

- Compiles the graph via `build_report_graph(make_report_tools(db_path))`
  (`build_report_graph` is the function that constructs the `StateGraph`, adds
  the two nodes + conditional edge, and `.compile()`s it).
- Invokes it with `config = {"configurable": {"model": model},
  "callbacks": get_langfuse_callbacks()}` and an initial `ReportState`.
- Maps the final state → `ReportResult` (`text`, `style`, `revision_count`,
  `approved`, `tool_log`, `trace_url: str | None`).

---

## 5. Data tools — `report/tools.py`

`make_report_tools(db_path)` returns a list of LangChain `@tool` objects, each a
thin wrapper around an existing function in
[`packages/core/spotify_core/db/queries.py`](../../../packages/core/spotify_core/db/queries.py).
`db_path` is bound via closure; the LLM only ever supplies `start_date` /
`end_date`.

| Tool | Wraps |
|---|---|
| `get_listening_summary` | `get_listening_summary` |
| `get_top_artists` | `get_top_artists` |
| `get_top_tracks` | `get_top_tracks` |
| `get_daily_activity_pattern` | `get_daily_activity_pattern` |
| `get_listening_trend` | `get_daily_trend` / `get_weekly_trend` / `get_monthly_trend`, picked by span (same three-tier rule as the dashboard) |

Each tool has a clear docstring (the LLM uses it as the tool description) and
returns the plain `list`/`dict` the query already produces.

---

## 6. Provider abstraction — `report/models.py`

```python
def build_chat_model(provider: str, model: str) -> BaseChatModel: ...
```

- The factory dispatches on `provider` ∈ `{"google", "openai", "anthropic"}`.
- **Provider rollout**: `google` (`ChatGoogleGenerativeAI`) is **implemented
  first** — it is the only working branch in v1. The `openai`
  (`ChatOpenAI`) and `anthropic` (`ChatAnthropic`) branches are written as
  skeletons that `raise NotImplementedError` with a `# TODO` comment. The
  signature, dispatch structure, and `BaseChatModel` return type are final, so
  enabling the other two later is a localized change.
- Raises a clear `ValueError` if the chosen provider's API key is not in the
  environment, so the UI can show actionable guidance.
- The model instance is passed into the graph through
  `config["configurable"]["model"]`; the graph never hard-codes a provider, so
  swapping models needs no graph rebuild — this is the seam for later model
  comparison.

The same model is used for both the drafter and the reviewer (one model per
run) — that single model is what a comparison run varies.

---

## 7. Langfuse — `report/observability.py`

```python
def get_langfuse_callbacks() -> list: ...
```

- If `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are all
  present → returns `[langfuse.langchain.CallbackHandler()]`.
- If any are missing → returns `[]`; the graph runs normally, untraced.
- The handler is passed in `config["callbacks"]`, so it captures the full run:
  drafter tool calls, token usage, reviewer verdicts, revision count.
- When tracing is active, `generate_report` surfaces the trace URL in
  `ReportResult.trace_url` for a UI link.

---

## 8. Playlist — `report/playlist.py`

The playlist is a **post-report action** and is **rule-based — no LLM, no graph
node**. Selecting "top tracks for the period" from `history.db` and templating a
name leaves no meaningful decision for a model to make; a deterministic function
is simpler, instant, free, and fully testable, and removes any hallucination
risk.

```python
def build_playlist_proposal(
    *, db_path: str, style: str, start_date: str, end_date: str,
    limit: int = 30,
) -> PlaylistProposal: ...
```

1. Calls `get_top_tracks(db_path, limit=limit, start_date=..., end_date=...,
   show_track_id=True)` — the user's most-played tracks for the period.
2. Filters the rows to genuine `spotify:track:` URIs (podcast episodes and any
   missing/malformed URI are dropped).
3. Returns `PlaylistProposal` (`name: str`, `description: str`,
   `track_uris: list[str]`). `name` and `description` are **templated** from the
   `style` and the date range — e.g. monthly_review → `「{start} ~ {end} 聽歌回顧」`,
   roast → a cheekier template. No model call.

`PlaylistProposal` is shown in the UI for review *before* anything is written to
Spotify. If no eligible tracks exist for the period, the function returns a
proposal with an empty `track_uris`; the UI then shows an info notice instead of
offering the create button.

### Creating the playlist

On explicit user confirmation, the web layer builds an authenticated client and
calls the existing facade:

- `SpotifyClient(tokens_db_path, user_id, client_id, fernet_key)` — same
  constructor `apps/mcp` uses in `make_client`; credentials come from the
  already-existing `get_sync_args()` path in `spotify_web/config.py`.
- `SpotifyToolFacade(...).create_playlist(name, track_uris, description)` from
  [`spotify_facade.py`](../../../packages/core/spotify_core/spotify_utils/spotify_facade.py)
  — creates a private playlist and adds the tracks, returning
  `{playlist_id, url, track_count}`.

The web app calls the core facade directly (not the MCP tool) — consistent with
the `apps/web` → `packages/core`-only import rule.

---

## 9. UI — `apps/web/ui/ai_block.py` (new)

`render_ai_block(default_start: str, default_end: str)` renders, below the
existing dashboard sections (one new call at the end of `render_dashboard()`):

1. **Header** — `st.divider()` + `st.subheader("🤖 AI 聽歌分析")`.
2. **Controls row**:
   - **Style selector** — 4 options, each mapping to a drafter template:
     📅 `月度回顧` (`monthly_review`), 🔥 `毒舌` (`roast`),
     😊 `溫和` (`gentle`), 🎼 `專業樂評` (`critic`).
   - **Date range** — its own start/end `st.date_input`s, defaulting to the
     dashboard's current period.
   - **Model dropdown** — lists only models whose provider key is configured
     (from `get_llm_config()`).
3. **Generate button** → spinner → `generate_report(...)`; the result is stored
   in `st.session_state`.
4. **Report display** — `st.markdown(result.text)` + a caption: model used,
   revisions, approved/cap-hit status, the tools the drafter called (from
   `tool_log`), and a Langfuse trace link when available.
5. **Playlist sub-flow** — only shown once a report exists:
   - Button `🎵 產生回顧 playlist` → `build_playlist_proposal(...)` (rule-based,
     instant); the `PlaylistProposal` is stored in `st.session_state`.
   - The proposed name, description, and tracklist are rendered for review.
   - A separate confirm button `在 Spotify 建立此 playlist` performs the actual
     creation; on success, `st.success` with the playlist URL.

State across reruns lives in `st.session_state` (report result, playlist
proposal). Nothing is persisted to disk.

---

## 10. Config & setup

### 10.1 `apps/web/spotify_web/config.py` (extend)

- `get_llm_config() -> dict` — inspects the environment for provider keys and
  returns the available `(provider, model)` choices + a default, driving the
  model dropdown. In v1 only `GOOGLE_API_KEY` yields usable choices;
  `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are recognised but their models are
  marked unavailable (matches the §6 provider rollout).
- `get_langfuse_config() -> dict | None` — returns Langfuse keys if all present,
  else `None`.
- A helper to build the authenticated `SpotifyClient` for playlist creation,
  reusing the `get_sync_args()` credential resolution.

Env loading keeps the existing pattern (`ensure_dotenv_loaded()` from
`spotify_core.env`).

### 10.2 In-app settings panel (`apps/web`)

The AI feature's keys are configured **inside the web app** — no MCP wizard
change, keeping AI setup self-contained in `apps/web` (see §3).

- A `⚙️ AI 設定` panel (an `st.expander` in the AI block, or a sidebar section)
  with a form for the LLM provider key (Google in v1) and the optional Langfuse
  keys (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`).
- On submit, the values are written to the platform config `.env`
  (`paths.env_file()`) and re-loaded via `ensure_dotenv_loaded()`.
- The panel pre-fills from currently-set values (masked) and shows which keys
  are present.
- All keys are optional: without an LLM key the generate controls are disabled
  and the panel is surfaced as the call to action; without Langfuse keys the
  graph still runs, untraced.

### 10.3 Dependencies

Add to a new `report` optional-dependency extra in `packages/core/pyproject.toml`
(and the root `pyproject.toml`):

- `langfuse`

`langchain-google-genai` (the v1 provider) and `langchain-openai` are already
present. `langchain-anthropic` is **deferred** — added only when the Anthropic
provider branch (§6) is implemented.

### 10.4 New environment variables

```bash
# AI report block — all optional; absence degrades gracefully
OPENAI_API_KEY=
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
```

Documented in `.env.example` and `CLAUDE.md`.

---

## 11. Error & empty-state handling

- **No LLM key configured** — the AI block disables the generate controls and
  surfaces the `⚙️ AI 設定` panel (§10.2) as the call to action.
- **Empty DB** (`is_history_empty`) — the AI block shows an info notice and is
  disabled (consistent with the dashboard's empty-state).
- **Graph / report exceptions** — caught in the UI, shown via `st.error`; the
  rest of the dashboard stays usable.
- **Reviewer never approves** — the `revision_count >= 2` cap always terminates
  the graph; the UI notes the report hit the revision cap.
- **Langfuse keys absent** — silent no-op, no error.
- **Playlist — no eligible tracks for the period** — `build_playlist_proposal`
  returns an empty `track_uris`; the UI shows an info notice and no create
  button.
- **Playlist — no OAuth tokens** — `create_playlist` raises; caught and shown as
  a friendly "run the setup wizard first" error.
- **Playlist — other API errors** — caught, logged, shown via `st.error`.

---

## 12. Testing (TDD)

Tests are written before the implementation.

- **`tests/core/` — report tools** — `make_report_tools` wrappers return the
  expected shapes against a temporary SQLite DB seeded with fixture rows;
  date-range passthrough works.
- **`tests/core/` — model factory** — `build_chat_model` returns
  `ChatGoogleGenerativeAI` for `google`, raises `ValueError` on a missing key,
  and raises `NotImplementedError` for the `openai` / `anthropic` skeletons.
- **`tests/core/` — graph** — with a fake/stub `BaseChatModel`: the drafter
  produces a draft and records its tool calls in `tool_log`; the reviewer
  rejects once then approves; the revision cap (≤ 2 rejections, ≤ 3 drafter
  passes) is enforced; `final_report` and `tool_log` are set on the result.
- **`tests/core/` — playlist** — `build_playlist_proposal` selects top tracks
  for the range, filters non-`spotify:track:` URIs, templates the name per
  style, and returns an empty `track_uris` (no crash) when the period has no
  eligible tracks.
- **Streamlit rendering** — not unit-tested; verified manually via the `.bat`
  launcher.

---

## 13. Out of scope / future work

- Desktop packaging (`pywebview` + `PyInstaller`) — separate spec.
- **Full app / wizard decoupling** — extracting the shared setup wizard (OAuth,
  credentials, history import) out of `apps/mcp` into `spotify_core` so
  `apps/web` and `apps/mcp` install and set up fully independently — separate
  spec.
- OpenAI / Anthropic provider branches (skeletons land in v1; §6).
- Web search tool for the drafter.
- User-authored custom tone prompts.
- Report persistence / a browsable report history.
- LLM-curated playlists / playlists built from tracks outside the user's
  history.
- The Chainlit chatbot migration (unrelated; `agent/` untouched).
