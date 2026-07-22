# Spotify AI Analytics

[English](#spotify-ai-analytics) ｜ [中文](#中文版說明)

A Spotify analytics toolkit — Cloudflare D1 is the source of truth for
listening history (kept in sync hourly by a GitHub Actions cron), the MCP
server for Claude Desktop/Code reads a local SQLite cache, and an optional
LangGraph pipeline generates AI listening reports.

> **Legacy docs & App** (original Streamlit web app): see the [`deploy` branch](../../tree/deploy).

---

## What Can It Do?

- **MCP:**
  - **Analytics** — ask Claude things like "What were my top artists last month?" or "How has my listening changed since 2023?"
  - **Playback control** — play, pause, skip, set volume, add to queue (Spotify Premium required)
  - **AI reports** — LangGraph-powered drafter/reviewer pipeline generates weekly or monthly listening reviews (needs the `[report]` extra)
- **Cloud sync:** an hourly GitHub Actions cron pulls recent plays from the Spotify API and writes them to Cloudflare D1 through a Worker; your PC never needs to be on. See [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (the wizard walks you through creating one)

---

## MCP Server Setup (Claude Desktop)

This project isn't published to PyPI — run it from a checkout of this repo.

### 1. Run the setup wizard

```bash
git clone https://github.com/wcnoname5/spotify-ai-analytics.git
cd spotify-ai-analytics
uv sync
uv run spotify-mcp setup
```

The wizard walks you through each step (already-completed steps are skipped automatically):

1. Create a Spotify developer app and paste the Client ID
2. OAuth login (opens your browser)
3. Import listening history (from Spotify's JSON export, or sync recent plays)
4. Register the MCP server with Claude Desktop

### 2. Connect Claude Desktop

After the wizard finishes, it prints a JSON snippet like this:

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/spotify-ai-analytics", "spotify-mcp", "serve"]
    }
  }
}
```

To add it to Claude Desktop:

1. Open Claude Desktop, click the menu (☰) in the top-left
2. Go to **Developer > Open App Config File...** to open `claude_desktop_config.json`
  > (If developer mode is not activated yet, go to **Help > Troubleshooting > Enable Developer Mode** first)
3. Paste the snippet above (merge into the existing `mcpServers` object if you have other servers)
4. Click **Developer > Reload MCP Configuration** (or restart Claude Desktop)
5. In a new chat, click **+ > Connectors** — you should see **spotify-mcp** in the list

### 3. Try it out

Click **+ > Connectors > Listening Report Generator** to generate your personal listening report, or just ask Claude about your listening history.

---

## AI Reports

AI report generation is an optional extra — the MCP server works without it.

### Install

```bash
uv sync --extra report
```

This enables two additional (optional) wizard steps:

- **LLM provider key** — choose [Google](https://aistudio.google.com/app/api-keys) (recommended, free tier with AI Studio) or OpenAI.
- **Langfuse keys** — optional observability for the AI report pipeline. Skip if you don't use Langfuse.

You can always add or change these keys later in your `.env` file (run `spotify-mcp doctor` to find it).

### Keeping history up to date

Sync the latest plays (up to 50) from Spotify's API:

```bash
uv run spotify-mcp sync
```

> Since Spotify API can only fetch up to 50 recent plays, this sync command has a limit of 50, too.

If you've set up the cloud pipeline (`docs/DEPLOY.md`), history syncs hourly
on its own via GitHub Actions — this command is only needed for the purely
local flow.

## CLI Reference

| Command | Description |
|---|---|
| `spotify-mcp setup` | Interactive setup wizard (skips completed steps) |
| `spotify-mcp serve` | Start the MCP server over stdio (used by Claude Desktop) |
| `spotify-mcp sync` | Sync recent plays from Spotify API |
| `spotify-mcp doctor` | Check environment readiness (JSON report) |
| `spotify-mcp import-history` | Import from Spotify's JSON data export |
| `spotify-mcp reauth` | Re-run OAuth flow |
| `spotify-mcp doctor` | Check readiness; also shows config/data directory locations |
| `spotify-mcp cloud pull` | Refresh the local cache from D1 |
| `spotify-mcp --help` | List all options and commands |
| `spotify-mcp --version` | Show the installed version and exit |

---

## Tech Stack

| Layer | Choice |
|---|---|
| MCP framework | FastMCP (Python MCP SDK) |
| Cloud sync | Cloudflare D1 + Worker (TypeScript), driven by an hourly GitHub Actions cron |
| AI reports | LangGraph (drafter → reviewer pipeline) |
| Observability | Langfuse (optional) |
| Local storage | SQLite (read-only sync cache of D1 + encrypted token store) |
| Data processing | Polars + Pydantic |
| OAuth | Authorization Code with PKCE |

---

## Project Layout

```
packages/core/        # Shared library: analytics, db, report pipeline, spotify_client
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server + CLI
worker/               # Cloudflare Worker (TypeScript) + D1 migrations
scripts/              # Cron sync, local sync, one-off migration scripts
data/                 # Spotify Listening Records JSON Data example template
```

---

## 中文版說明

[English](#spotify-ai-analytics) ｜ [中文](#中文版說明)

**Spotify AI 分析工具**是一套 Spotify 分析工具包：Cloudflare D1 是收聽紀錄的唯一真實來源（由 GitHub Actions 排程每小時同步），用於 Claude Desktop/Code 的 MCP 伺服器讀取本地 SQLite 快取，並可選用 LangGraph 流程生成 AI 收聽報告。

> **舊版文件與應用程式**（原始 Streamlit 網頁版）：請見 [`deploy` 分支](../../tree/deploy)。

---

### 功能介紹

- **MCP 伺服器：**
  - **分析** — 透過 Claude 提問，例如「上個月我最常聽的歌手是誰？」或「我的收聽習慣從 2023 年以來有什麼變化？」
  - **播放控制** — 播放、暫停、跳曲、設定音量、加入佇列（需要 Spotify Premium）
  - **AI 報告** — 由 LangGraph 框架建造草稿撰寫/審閱流程，生成每週、每月或者自訂時間的收聽報告（需要 `[report]` 套件）
- **雲端同步：** GitHub Actions 排程每小時透過 Worker 從 Spotify API 拉取最新播放紀錄並寫入 Cloudflare D1；本機不需要保持開機。詳見 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

---

### 系統需求

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)（套件管理器）
- 建立一個 [Spotify Developer](https://developer.spotify.com/dashboard) 應用程式（精靈會引導你完成建立步驟）

---

### MCP 伺服器設定（Claude Desktop）

本專案未發佈至 PyPI — 請從此 repo 的原始碼執行。

#### 1. 執行安裝精靈

```bash
git clone https://github.com/wcnoname5/spotify-ai-analytics.git
cd spotify-ai-analytics
uv sync
uv run spotify-mcp setup
```

精靈會逐步引導你完成設定（已完成的步驟會自動略過）：

1. 建立 Spotify 開發者應用程式並貼上 Client ID
2. OAuth 登入（會自動開啟瀏覽器）
3. 匯入收聽紀錄（從 Spotify 的 JSON 匯出，或同步最近的播放紀錄）
4. 將 MCP 伺服器註冊至 Claude Desktop

#### 2. 連接 Claude Desktop

精靈完成後，會印出如下的 JSON 片段：

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/spotify-ai-analytics", "spotify-mcp", "serve"]
    }
  }
}
```

新增至 Claude Desktop 的步驟：

1. 開啟 Claude Desktop，點選左上角的選單（☰）
2. 前往 **Developer > Open App Config File...** 開啟 `claude_desktop_config.json`
  > （若尚未啟用開發者模式，請先前往 **Help > Troubleshooting > Enable Developer Mode**）
3. 貼上上方的 JSON 片段（若已有其他伺服器，請合併至現有的 `mcpServers` 物件中）
4. 點選 **Developer > Reload MCP Configuration**（或重新啟動 Claude Desktop）
5. 在新對話中，點選 **+ > Connectors**，應可看見 **spotify-mcp**

#### 3. 開始使用

點選 **+ > Connectors > Listening Report Generator** 生成個人收聽報告，或直接向 Claude 詢問你的收聽紀錄。

---

### AI 報告

AI 報告生成為選用功能，MCP 伺服器不需要它也能正常運作。

#### 安裝

```bash
uv sync --extra report
```

啟用後，精靈會額外引導兩個選用步驟：

- **LLM 供應商金鑰** — 選擇 [Google](https://aistudio.google.com/app/api-keys)（推薦，AI Studio 有免費方案）或 OpenAI。
- **Langfuse 金鑰** — 為 AI 報告流程提供可觀測性，選用。若不使用 Langfuse 可略過。

你隨時可以在 `.env` 檔案中新增或修改這些金鑰（執行 `spotify-mcp doctor` 可找到檔案位置）。

#### 保持紀錄最新

從 Spotify API 同步最新的收聽紀錄（最多 50 筆）：

```bash
uv run spotify-mcp sync
```

> 由於 Spotify API 最多只能取得最近 50 筆播放紀錄，sync 指令同樣有此限制。

若已設定雲端流程（`docs/DEPLOY.md`），收聽紀錄會透過 GitHub Actions 每小時自動同步；此指令僅在純本地流程下才需要。

---

### CLI 指令參考

| 指令 | 說明 |
|---|---|
| `spotify-mcp setup` | 互動式安裝精靈（已完成步驟自動略過） |
| `spotify-mcp serve` | 透過 stdio 啟動 MCP 伺服器（供 Claude Desktop 使用） |
| `spotify-mcp sync` | 從 Spotify API 同步最近的播放紀錄 |
| `spotify-mcp doctor` | 檢查環境就緒狀態（輸出 JSON 報告） |
| `spotify-mcp import-history` | 從 Spotify JSON 資料匯出檔匯入紀錄 |
| `spotify-mcp reauth` | 重新執行 OAuth 流程 |
| `spotify-mcp doctor` | 檢查環境是否就緒，同時顯示設定檔與資料目錄位置 |
| `spotify-mcp cloud pull` | 從 D1 更新本地快取 |
| `spotify-mcp --help` | 列出所有選項與指令 |
| `spotify-mcp --version` | 顯示已安裝的版本並結束 |

---

### 技術堆疊

| 層級 | 選擇 |
|---|---|
| MCP 框架 | FastMCP（Python MCP SDK） |
| 雲端同步 | Cloudflare D1 + Worker（TypeScript），由 GitHub Actions 每小時排程驅動 |
| LLM報告生成 | LangGraph（草稿 → 審閱流程） |
| 可觀測性 | Langfuse（選用） |
| 本地儲存 | SQLite（D1 的唯讀同步快取 + 加密金鑰儲存） |
| 資料處理 | Polars + Pydantic |
| OAuth | Authorization Code with PKCE |

---

### 專案結構

```
packages/core/        # 共用函式庫：分析、資料庫、報告流程、spotify_client
packages/dataloader/  # 資料匯入（Polars + Pydantic）
apps/mcp/             # MCP 伺服器 + CLI
worker/               # Cloudflare Worker（TypeScript）+ D1 migrations
scripts/              # 排程同步、本地同步、一次性遷移腳本
data/                 # Spotify Listening Records JSON Data 範例樣板
```