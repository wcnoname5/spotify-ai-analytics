# Phase 1 MCP Migration — Analysis & Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 評估並規劃將現有 Streamlit app 遷移至 ARCHITECTURE.md 定義的 monorepo 結構，同時在不中斷現有前端的前提下完成 Phase 1 MCP server。

**Architecture:** uv workspace monorepo，核心邏輯放 `packages/`，應用層放 `apps/`，MCP 與 Web 共用同一套 core packages。

**Tech Stack:** uv workspace, Python packages, LangGraph, MCP SDK, SQLite, Polars, Streamlit (maintained)

---

## Part 1 — 現有 src/ 模組分析

### 1.1 模組職責與依賴關係圖

```
config/settings.py          ← 零外部 local import（底層）
    ↑
dataloader/
  models.py                 ← config.settings
  data_loader.py            ← config.settings, dataloader.models
  analysis_functions.py     ← 純 polars，零 local import
  __init__.py               ← 重新 export 以上所有 public API
    ↑
spotify_agent/
  schemas.py                ← 零 local import（Pydantic models）
  prompts.py                ← 零 local import（字串常數）
  state.py                  ← spotify_agent.schemas
  tools.py                  ← spotify_agent.schemas, dataloader.*
  nodes.py                  ← spotify_agent.{state,schemas,prompts}, utils.agent_utils
  graph.py                  ← spotify_agent.{state,nodes}
    ↑
utils/
  loggings.py               ← config.settings（PROJECT_ROOT）
  agent_utils.py            ← spotify_agent.tools, dataloader.*, config.settings
    ↑
app/（Streamlit UI）
  main_page.py              ← dataloader, app.{chatbot_page,dashboard}, utils.*, config
  chatbot_page.py           ← spotify_agent.graph, utils.agent_utils
  dashboard.py              ← dataloader.*, app.{track_analysis,time_analysis}
  track_analysis.py         ← dataloader.*
  time_analysis.py          ← dataloader.*
```

**重要觀察：**
- `src/analytics/__init__.py` 是空的。分析函數實際上在 `src/dataloader/analysis_functions.py`。
- `utils/agent_utils.py` 是 Streamlit-specific 的 resource manager（用 `st.session_state`），移到 MCP 時需重寫。
- `config/settings.py` 被幾乎每個模組直接 import，是最廣泛的橫切依賴。

### 1.2 LangGraph Graph 結構

```
Entry: IntentParser
         │
         ▼ (conditional: has tool_plan?)
    ┌────┴────┐
    │ Yes     │ No
    ▼         ▼
ToolExecute  Analyst ─→ END
    │
    ▼
  Analyst ─→ END
```

**Nodes：**
| Node | 函數 | 職責 |
|------|------|------|
| `IntentParser` | `intent_parser` | structured output → `IntentPlan`（intent_type + tool_plan） |
| `ToolExecute` | `data_fetch` | bind tools, LLM tool call, retry logic → ToolMessages |
| `Analyst` | `analyst_node` | synthesize final response from tool results + intent |

**State (`AgentState`)：**
```python
input: str
messages: Annotated[Sequence[BaseMessage], operator.add]  # reducer pattern
intent: Literal['factual_query','insight_analysis','recommendation','other']
plan: Optional[IntentPlan]
tool_results: List[Any]
final_response: Optional[str]
retry_count: Optional[int]
```

**現有 Tools（5 個）：**
1. `get_summary_stats()`
2. `get_top_artists(limit, start_date, end_date)`
3. `get_top_tracks(limit, artist, start_date, end_date)`
4. `free_query(where, select, limit, sort_by, descending)`
5. `free_aggregate(group_by, metrics, where, sort_by, descending, limit)`

---

## Part 2 — Migration Difficulty 評估

### 2.1 Zero Changes（直接搬移）

| 現有路徑 | 新路徑 | 理由 |
|---------|--------|------|
| `src/dataloader/analysis_functions.py` | `packages/dataloader/analysis_functions.py` | 零 local import，純 Polars |
| `src/dataloader/models.py` | `packages/dataloader/models.py` | 只 import stdlib + pydantic |
| `src/spotify_agent/schemas.py` | `packages/core/agent/schemas.py` | 只 import pydantic |
| `src/spotify_agent/prompts.py` | `packages/core/agent/prompts.py` | 純字串常數 |
| `src/app/*.py` | `apps/web/ui/*.py` | Phase 2 搬移，現在不動 |

### 2.2 只需改 Import Paths（低風險）

| 現有路徑 | 新路徑 | 需改的 import |
|---------|--------|--------------|
| `src/dataloader/data_loader.py` | `packages/dataloader/data_loader.py` | `from config.settings import settings` → `from spotify_core.config import settings` 或用 constructor 注入 |
| `src/dataloader/__init__.py` | `packages/dataloader/__init__.py` | 相對 import 調整 |
| `src/spotify_agent/state.py` | `packages/core/agent/state.py` | `.schemas` → 相對 import 調整 |
| `src/spotify_agent/graph.py` | `packages/core/agent/graph.py` | 相對 import 調整 |
| `src/spotify_agent/nodes.py` | `packages/core/agent/nodes.py` | `utils.agent_utils` → 需重構（見下） |
| `src/spotify_agent/tools.py` | `packages/core/agent/tools.py` | `dataloader.*` → package import |
| `src/utils/loggings.py` | 移至 `packages/core/` 或 `apps/web/` | `config.settings.PROJECT_ROOT` 依賴 |

### 2.3 需要重構（介面不符）

| 模組 | 問題 | 重構方向 |
|------|------|---------|
| `src/utils/agent_utils.py` | 強依賴 `st.session_state`，無法在 MCP 環境使用 | 拆成兩層：(a) `packages/core/` 的 pure resource factory，(b) `apps/web/` 的 Streamlit session wrapper |
| `src/config/settings.py` | 所有模組直接 import，耦合太緊 | 移至 `packages/core/config.py`，或讓各 package 用 constructor injection 接收 settings |
| `src/spotify_agent/nodes.py` | 呼叫 `utils.agent_utils.get_resources()`，耦合 Streamlit | nodes.py 應接收 llm + tools 作為參數，不主動 resolve |
| `src/analytics/__init__.py` | 空的，但 ARCHITECTURE 說要從這裡 migrate | 實際上要把 `dataloader/analysis_functions.py` 的內容 **拆出** 到 `packages/core/analytics/` |

### 2.4 全新模組（無現有對應）

| 新模組 | 工作量 | 說明 |
|--------|--------|------|
| `packages/core/spotify_client/` | 高 | OAuth PKCE + token storage + API wrappers，全新 |
| `packages/core/memory/` | 中 | SqliteSaver + SqliteStore wiring，API 簡單但需測試 |
| `packages/core/db/` | 低 | SQLite schema migration，純 DDL |
| `apps/mcp/server.py` | 中 | MCP SDK wrapping，需了解 SDK pattern |
| `apps/mcp/auth.py` | 高 | PKCE flow + local HTTP callback server |

---

## Part 3 — uv Workspace pyproject.toml 結構

### Root `pyproject.toml`

```toml
[project]
name = "spotify-ai-analytics"
version = "0.1.0"
requires-python = ">=3.11"

[tool.uv.workspace]
members = [
    "packages/core",
    "packages/dataloader",
    "apps/mcp",
    "apps/web",
]

# 讓 root-level 指令（如 uv run pytest）可以 resolve workspace members
[tool.uv.sources]
spotify-core = { workspace = true }
spotify-dataloader = { workspace = true }

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

### `packages/core/pyproject.toml`

```toml
[project]
name = "spotify-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "langchain-openai>=0.2",
    "langchain-google-genai>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "cryptography>=42.0",     # token encryption
    "httpx>=0.27",            # Spotify API calls
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### `packages/dataloader/pyproject.toml`

```toml
[project]
name = "spotify-dataloader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "polars>=1.0",
    "pydantic>=2.0",
    "spotify-core",           # 需要 config/settings
]

[tool.uv.sources]
spotify-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**注意：** 如果要避免 dataloader → core 的循環依賴，可以把 `settings.py` 獨立成 `packages/config/` 或讓 `SpotifyDataLoader.__init__` 接收 `data_path` 參數，完全解耦 config 依賴。**建議後者**（constructor injection），因為更易測試。

### `apps/mcp/pyproject.toml`

```toml
[project]
name = "spotify-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0",               # MCP Python SDK
    "spotify-core",
    "spotify-dataloader",
]

[tool.uv.sources]
spotify-core = { workspace = true }
spotify-dataloader = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project.scripts]
spotify-mcp = "spotify_mcp.server:main"
```

### `apps/web/pyproject.toml`

```toml
[project]
name = "spotify-web"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "streamlit>=1.35",
    "plotly>=5.0",
    "spotify-core",
    "spotify-dataloader",
]

[tool.uv.sources]
spotify-core = { workspace = true }
spotify-dataloader = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project.scripts]
spotify-web = "spotify_web.main_page:main"
```

---

## Part 4 — 執行順序建議（維持 Streamlit 的前提下完成 Phase 1）

### 核心策略

**雙軌並行：** 用 git branch 隔離新結構，Streamlit 在 `main` 繼續可用，`phase1-mcp` branch 做 monorepo 重構。CI 確保兩個 branch 都 pass tests 後 merge。

### Stage 0：準備（1天）

```
目標：確立 baseline，確保現有 Streamlit 有測試覆蓋
```

- [ ] 補寫 smoke test：`tests/test_smoke.py` 測試現有 agent invoke（用 fixture 避免真實 API call）
- [ ] 確認 `uv run streamlit run src/app/main_page.py` 在 Windows 上正常執行
- [ ] 建 `phase1-mcp` branch

### Stage 1：Monorepo 骨架（2天）

```
目標：建立 uv workspace，現有 src/ 程式完整搬移，Streamlit 繼續可用
```

**Step 1a：建目錄結構**
```
mkdir -p packages/core/{spotify_client,analytics,agent,memory,db}
mkdir -p packages/dataloader
mkdir -p apps/{mcp,web/ui}
```

**Step 1b：寫各 pyproject.toml**（見 Part 3 結構）

**Step 1c：搬移 zero-change 模組**（按依賴順序，由底層往上）
1. `src/dataloader/models.py` → `packages/dataloader/`
2. `src/dataloader/analysis_functions.py` → `packages/dataloader/`
3. `src/config/settings.py` → `packages/core/config.py`（調整 package name）
4. `src/dataloader/data_loader.py` → `packages/dataloader/`（改 config import）
5. `src/spotify_agent/schemas.py` + `prompts.py` → `packages/core/agent/`
6. `src/spotify_agent/state.py` + `graph.py` + `tools.py` → `packages/core/agent/`
7. `src/utils/loggings.py` → `packages/core/logging.py`

**Step 1d：重構 `agent_utils.py`**（關鍵一步）
- 拆成：
  - `packages/core/agent/resources.py`：pure factory（接受 api_key, loader 作為參數，不碰 st.session_state）
  - `apps/web/ui/session.py`：Streamlit session wrapper（呼叫 resources.py，管理 st.session_state）
- `nodes.py` 改為接受 `llm` + `tools` 作為參數注入（dependency injection）

**Step 1e：更新 `src/app/*.py` 的 import paths**
- 把 `from dataloader import ...` 改成 `from spotify_dataloader import ...`
- 把 `from spotify_agent import ...` 改成 `from spotify_core.agent import ...`
- 把 `from utils.agent_utils import ...` 改成 `from spotify_web.session import ...`

**驗收：** `uv run streamlit run apps/web/ui/main_page.py` 正常啟動

> 這一步可以用 `src/` 暫時留著，同時讓 `apps/web/ui/` 指向新路徑，逐步 cut over。

### Stage 2：DB + Config 層（2天）

```
目標：建 SQLite schema，讓後面的 spotify_client 有地方存 tokens
```

- [ ] `packages/core/db/schema.py`：`listening_history`, `spotify_tokens` 表的 CREATE TABLE
- [ ] `packages/core/db/migrations.py`：自動建表 + 未來 migration 的簡單機制（不用 Alembic，純 SQLite pragma）
- [ ] 單元測試：`tests/core/test_db.py`

### Stage 3：Spotify Client + OAuth（3-4天，最複雜）

```
目標：完整 PKCE OAuth flow，token 加密存 SQLite，typed API wrappers
```

- [ ] `packages/core/spotify_client/pkce.py`：generate code_verifier/challenge
- [ ] `packages/core/spotify_client/auth.py`：open browser → 127.0.0.1 callback server（`http.server` 或 `fastapi`） → exchange code → save token
- [ ] `packages/core/spotify_client/token_store.py`：加密讀寫 `spotify_tokens` table
- [ ] `packages/core/spotify_client/client.py`：Spotify API 的 typed wrappers（先實作 recently-played, now-playing, playback control）
- [ ] 測試：mock httpx → test token refresh logic

*Comment:* 希望這邊可以寫一個小Scirpt讓使用者不需要LLM也可以簡單的隨時更新DB跟著最新的聆聽紀錄動態聆聽紀錄(GET `https://api.spotify.com/v1/me/player/recently-played` endpoint)

### Stage 4：Memory Layer（2天）

```
目標：SqliteSaver + SqliteStore 接上現有 agent
```

- [ ] `packages/core/memory/checkpointer.py`：SqliteSaver wrapper
- [ ] `packages/core/memory/store.py`：SqliteStore wrapper + LTM namespace helpers
- [ ] `packages/core/agent/graph.py`：加 checkpointer 到 `workflow.compile(checkpointer=...)`
- [ ] 測試：跨 thread_id 的 memory isolation

### Stage 5：新 Agent Tools + Playback（2天）

```
目標：新增 playback_control / playlist_create / sync_history intent + tools
```

- [ ] `packages/core/agent/state.py`：新增 intent types
- [ ] `packages/core/agent/tools.py`：新增 `play_track`, `pause`, `skip`, `set_volume`, `add_to_queue`, `sync_recent_history`, `get_now_playing`
- [ ] 測試：mock spotify_client

### Stage 6：MCP Server（2天）

```
目標：MCP server 包裝 core tools，可接入 Claude Desktop
```

- [ ] `apps/mcp/server.py`：用 MCP SDK 把 core tools 包成 MCP tools
- [ ] `apps/mcp/auth.py`：啟動時 check token，沒有則觸發 PKCE flow
- [ ] `apps/mcp/README.md`：Claude Desktop 設定步驟

### Stage 7：End-to-End 測試（1天）

- [ ] 在 Claude Desktop 測試所有 MCP tools
- [ ] 確認 Streamlit app 在新結構下正常運作
- [ ] `uv run pytest tests/` 全部 pass

---

## 關鍵決策點（需在 Stage 1 前確認）

| 決策 | 選項 A | 選項 B | 建議 |
|------|--------|--------|------|
| Config 依賴 | `packages/core/config.py` 共用 | Constructor injection | **B：injection 更易測試，解耦** |
| agent_utils 拆法 | 只拆 Streamlit 部分 | 完整重寫為 DI pattern | **A：最小破壞現有 Streamlit** |
| analytics 放哪裡 | 留在 `packages/dataloader/` | 拆到 `packages/core/analytics/` | **A for now（YAGNI）；Phase 2 再拆** |
| src/ 保留期 | 立刻刪除 | 當 `apps/web/` 驗收後再刪 | **B：安全** |
