# Chatbot + Dashboard Platform — Roadmap & Architecture Decisions

**Date:** 2026-05-15
**Status:** Active. Captures cross-cutting decisions for the chatbot + dashboard local app.
**Owner:** wcnoname5

This document records the architectural decisions made during brainstorming for the local chatbot + dashboard app built on top of the existing `spotify-analytics` MCP server. It is the index for the sub-project specs that follow.

---

## 1. Goals

Build a local-only desktop-style app that:

1. **Chatbot page** — Claude-Code-style chat specialized in querying the user's Spotify history through the existing MCP tools. ReAct-based agentic workflow, with room for plan-validate / output-critic variants.
2. **Dashboard page** — keeps the existing Plotly-based listening-history visualizations.
3. **Skills system** — Anthropic-style markdown skills (the agent autonomously loads when relevant). First skill: "generate listening-analysis report".
4. **Long-term memory** — per-user preferences / history facts / feedback, surviving across conversations.
5. **Architecture-experiment platform** — every chat turn (and every offline eval run) records latency, token cost, tool calls, and (when available) accuracy, so different architectures (single-agent vs plan-validate vs critic vs full) and different models can be compared on equal footing.

The app is local-only in the sense of *not deployed as a public service*. Cloud LLM APIs and cloud tracing services (Langfuse Cloud) are acceptable.

---

## 2. Key architectural decisions

### 2.1 Tool layer: shared registry + dual adapter

A canonical Python tool registry lives in `packages/core/tools/`. The MCP server and the chatbot's LangChain agent each get a thin adapter that exposes the same registry. One source of truth, two interfaces.

**Why:** Future model comparisons need to call the same tools without IPC noise. Re-implementing tools in two places (MCP + LangChain `@tool`) creates drift the moment we add a new tool.
**Trade-off accepted:** A 1–2 day refactor now, while the tool count is small. Doing it later — after Skills and validation variants pile up — is much more expensive.

Sub-project: **A — Tool Registry** (see `2026-05-15-tool-registry-design.md`).

### 2.2 UI: Chainlit (chatbot) + Streamlit (dashboard)

The chatbot page migrates from Streamlit to **Chainlit**. The dashboard stays in Streamlit.

**Why Chainlit:** Async-native, designed for LLM chat UIs, first-class support for streaming, nested tool-call traces, and "thinking" indicators — i.e. the Claude-Code-style UX is essentially free. Streamlit's rerun-on-interaction model makes the same UX painful (MCP/stdio session lifecycle, async event loops, streaming partial tool results).
**Why keep Streamlit for dashboard:** Streamlit suits the dashboard's form-and-chart UX. The dashboard is being **rebuilt as a DB-backed app** — it reads `history.db` directly via SQL, replacing the older Polars/JSON dataframe path — see `2026-05-21-local-dashboard-design.md`. This work is **pulled forward** ahead of the chatbot sub-projects. The rebuilt dashboard ships its own double-click `.bat` launcher; the chatbot (Chainlit) runs as a separate process.

### 2.3 Agent architecture: variants as configs, not branches

The chatbot's agent graph is built by a single factory keyed off a `RunConfig`:

```python
@dataclass
class RunConfig:
    model: str               # e.g. "gpt-4o", "gemini-2.5-pro", "claude-haiku-4-5"
    architecture: str        # "single" | "plan_validate" | "critic" | "full"
    use_memory: bool
    skills_enabled: bool
    system_prompt_variant: str = "default"

def build_graph(cfg: RunConfig) -> CompiledGraph: ...
```

The MVP ships with `architecture="single"` only. New variants (`plan_validate`, `critic`, `full`) are added as additional graph factories that share node implementations where possible. **Adding a variant must never require touching the telemetry layer, the registry, the UI shell, or any earlier variant.**

**Why:** The user explicitly wants room to experiment with architectures and compare them. Treating variants as first-class configuration (not git branches or forks) is the only way that comparison stays apples-to-apples.

### 2.4 Telemetry: Langfuse Cloud

All LLM calls, tool calls, and agent runs are traced to **Langfuse Cloud** (free tier). The codebase wraps the LangChain / Anthropic / OpenAI SDKs with the Langfuse callback handlers from day one.

**Why Langfuse:**
- LLM-native trace tree (nested spans for ReAct loops, no extra plumbing)
- Built-in **Datasets** feature maps onto the golden test set use case
- `langfuse.score()` API records custom metrics (accuracy, "used correct tool", etc.) alongside latency/cost
- Self-host path remains available if cloud ever becomes a problem (`docker compose up`)

**Why Cloud over self-host as starting point:** Zero infra setup. The data being traced is the user's own Spotify analytics queries — no sensitivity concern that warrants self-hosting at this stage.

### 2.5 Evaluation: golden test set + Langfuse Datasets

A small hand-curated `data/eval/golden_v1.jsonl` (10–20 Q&A pairs) is built during sub-project B. Each entry includes the question, expected tool(s) to be called, and a flexible "expected answer" (keywords, numeric ranges, or LLM-as-judge rubric — to be decided in B's spec). The set is uploaded to Langfuse as a Dataset; each architecture/model variant is run against it and the results live as Experiments in Langfuse for direct UI comparison.

### 2.6 Skills: Anthropic-style

Skills live under `skills/` (project root or `packages/core/skills/` — decided in sub-project G's spec). Each skill is a directory containing a `SKILL.md` (frontmatter + body describing *when* and *how* to use it) plus optional Python scripts. A `SkillLoader` reads metadata at agent startup; the agent autonomously decides whether to load a skill's body based on the user's question.

First concrete skill (G milestone): **"Generate listening-analysis report"** — produces a structured markdown report from a user-specified time range, combining `get_listening_summary`, `get_top_artists`, `get_top_tracks`, and memory facts.

### 2.7 Memory: SqliteStore, not LangMem

Long-term memory uses LangGraph's `SqliteStore` directly, under `data/ltm.db`. This is consistent with the project rule in CLAUDE.md (LangMem has unacceptable p95 latency). Namespaces follow the existing convention:

```
("user:{user_id}", "preferences")
("user:{user_id}", "history_facts")
("user:{user_id}", "feedback")
```

Memory toggle (`use_memory: bool` in RunConfig) makes memory itself an architectural variable that the experiment platform can A/B.

---

## 3. Sub-project breakdown and priority

| # | Sub-project | Depends on | Rough size | Status |
|---|---|---|---|---|
| **A** | Tool Registry (`packages/core/tools/`) + MCP adapter | — | 1–2 days | spec being written |
| **B** | Experiment infrastructure: Langfuse wiring, `RunConfig`, headless eval CLI, golden test set v1 | A | 2 days | pending |
| **C** | Chainlit shell + single-agent baseline (uses A + B) | A, B | 2 days | pending |
| **D** | Architecture variants: `plan_validate`, `critic`, `full` | C | 1 day each | pending |
| **E** | Memory integration (SqliteStore wired into agent) | C | 2 days | pending |
| **F** | Multi-model adapters (OpenAI / Anthropic / Gemini / local) | A, B | 2 days | pending |
| **G** | Anthropic-style skills system + listening-report skill | C, E | 3–4 days | pending |
| **H** | Local DB-backed dashboard rebuild (`2026-05-21-local-dashboard-design.md`) — replaces the Polars/JSON dashboard, ships its own `.bat` launcher | — | ~3 days | spec done (2026-05-21); **pulled forward** |
| **I** | Experiment-results page (Langfuse experiment comparison UI) | B | 1–2 days | pending |

**Recommended execution order:** H (dashboard — independent, pulled forward) → A → B → C → (D ∥ E ∥ F) → G. Sub-project I follows once B lands. H was originally bundled with the experiment-results page; that page is now split out as I.

Each sub-project gets its own spec → plan → implementation cycle. This roadmap is updated as decisions evolve.

---

## 4. Non-goals (explicitly out of scope)

- **Multi-user deployment.** App is local-only; user_id is hard-coded or read from env.
- **Authentication beyond Spotify OAuth.** No login UI, no user accounts.
- **Replacing the MCP server.** The MCP server remains the canonical external interface (Claude Desktop / Claude Code continue to work, unchanged).
- **Re-implementing analytics.** Analytics logic stays in `packages/core/analytics/`; the registry only wraps it.
- **Production-grade auth/secrets management.** `.env` + Fernet for tokens is good enough for a local app.

---

## 5. Open questions to revisit per sub-project

- B: exact schema of `golden_v1.jsonl` (keyword match vs LLM-as-judge for answer correctness)
- C: how to launch Chainlit + Streamlit together (single command vs two terminals vs simple FastAPI launcher)
- D: whether `full` (plan-validate + critic combined) is one graph or composition of two
- G: skill discovery — eager load all metadata at startup, or lazy scan on first user message?

These are deferred to their owning sub-project's spec, not solved here.
