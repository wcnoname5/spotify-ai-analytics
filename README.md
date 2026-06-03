# Spotify AI Analytics

[English](#spotify-ai-analytics) ｜ [中文](#中文版說明)

A local-first Spotify analytics toolkit — MCP server for Claude Desktop/Code, a Streamlit dashboard with AI-generated listening reports, and a SQLite-backed data pipeline. All set up with a single CLI command.

> **Legacy docs & App** (original Streamlit web app): see the [`deploy` branch](../../tree/deploy).

---

## What Can It Do?

- **Common Feature:** A local SQLite database stores and syncs listening history data directly from Spotify.
- **MCP:**
  - **Analytics** — ask Claude things like "What were my top artists last month?" or "How has my listening changed since 2023?"
  - **Playback control** — play, pause, skip, set volume, add to queue (Spotify Premium required)
- **Dashboard and Report Generation:**
  - **Dashboard** — Plotly charts for listening trends, top artists/tracks, and activity patterns
  - **AI reports** — LangGraph-powered drafter/reviewer pipeline generates weekly or monthly listening reviews

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (the wizard walks you through creating one)

---

## MCP Server Setup (Claude Desktop)

### 1. Run the setup wizard

```bash
uvx --from spotify-analytics-mcp spotify-mcp setup
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
      "command": "uvx",
      "args": ["--from", "spotify-analytics-mcp", "spotify-mcp", "serve"]
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

## Dashboard & AI Reports

The dashboard is an optional extra — the MCP server works without it.

### Install

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp setup
```

Using the `[dashboard]` extra triggers two additional (optional) wizard steps:

- **LLM provider key** — choose [Google](https://aistudio.google.com/app/api-keys) (recommended, free tier with AI Studio) or OpenAI. Required for AI reports; the dashboard charts work without it.
- **Langfuse keys** — optional observability for the AI report pipeline. Skip if you don't use Langfuse.

You can always add or change these keys later in your `.env` file (run `spotify-mcp path` to find it).

### Launch

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard
```

### Keeping history up to date

Sync the latest plays (up to 50) from Spotify's API:

```bash
uvx --from spotify-analytics-mcp spotify-mcp sync
```

or click the Sync button on the top-right in dashboard view.

> Since Spotify API can only fetch up to 50 recent plays, this sync command has a limit of 50, too.

## CLI Reference

| Command | Description |
|---|---|
| `spotify-mcp setup` | Interactive setup wizard (skips completed steps) |
| `spotify-mcp serve` | Start the MCP server over stdio (used by Claude Desktop) |
| `spotify-mcp dashboard` | Launch the Streamlit dashboard (requires `[dashboard]` extra) |
| `spotify-mcp sync` | Sync recent plays from Spotify API |
| `spotify-mcp doctor` | Check environment readiness (JSON report) |
| `spotify-mcp import-history` | Import from Spotify's JSON data export |
| `spotify-mcp reauth` | Re-run OAuth flow |
| `spotify-mcp path` | Show config and data directory locations |
| `spotify-mcp --help` | List all options and commands |
| `spotify-mcp --version` | Show the installed version and exit |

---

## Tech Stack

| Layer | Choice |
|---|---|
| MCP framework | FastMCP (Python MCP SDK) |
| AI reports | LangGraph (drafter → reviewer pipeline) |
| Observability | Langfuse (optional) |
| Local storage | SQLite (spotify data + encrypted token store) |
| Data processing | Polars + Pydantic |
| Dashboard | Streamlit + Plotly |
| OAuth | Authorization Code with PKCE |

---

## Project Layout

```
packages/core/        # Shared library: analytics, db, report pipeline, spotify_client
packages/dataloader/  # Data ingestion (Polars + Pydantic)
apps/mcp/             # MCP server + CLI + Streamlit dashboard
data/                 # Spotify Listening Records JSON Data example template
```

---

## 中文版說明

[English](#spotify-ai-analytics) ｜ [中文](#中文版說明)

**Spotify AI 分析工具**是一套以本地為主的 Spotify 分析工具包，包含用於 Claude Desktop/Code 的 MCP 伺服器、搭載 AI 生成收聽報告的 Streamlit 儀表板，以及以 SQLite 為後端的資料管線，只需一個 CLI 指令即可完成設定。

> **舊版文件與應用程式**（原始 Streamlit 網頁版）：請見 [`deploy` 分支](../../tree/deploy)。

---

### 功能介紹

- **共同功能：** 本地 SQLite 資料庫可直接儲存並同步來自 Spotify 的收聽紀錄。
- **MCP 伺服器：**
  - **分析** — 透過 Claude 提問，例如「上個月我最常聽的歌手是誰？」或「我的收聽習慣從 2023 年以來有什麼變化？」
  - **播放控制** — 播放、暫停、跳曲、設定音量、加入佇列（需要 Spotify Premium）
- **儀表板與報告生成：**
  - **儀表板** — 以 Plotly 繪製收聽趨勢、熱門歌手/曲目及活躍模式圖表
  - **AI 報告** — 由 LangGraph 框架建造草稿撰寫/審閱流程，生成每週、每月或者自訂時間的收聽報告

---

### 系統需求

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)（套件管理器）
- 建立一個 [Spotify Developer](https://developer.spotify.com/dashboard) 應用程式（精靈會引導你完成建立步驟）

---

### MCP 伺服器設定（Claude Desktop）

#### 1. 執行安裝精靈

```bash
uvx --from spotify-analytics-mcp spotify-mcp setup
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
      "command": "uvx",
      "args": ["--from", "spotify-analytics-mcp", "spotify-mcp", "serve"]
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

### 儀表板與 AI 報告

儀表板為選用套件，MCP 伺服器不需要它也能正常運作。

#### 安裝

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp setup
```

加入 `[dashboard]` 套件後，精靈會額外引導兩個選用步驟：

- **LLM 供應商金鑰** — 選擇 [Google](https://aistudio.google.com/app/api-keys)（推薦，AI Studio 有免費方案）或 OpenAI。AI 報告需要此設定；儀表板圖表不需要。
- **Langfuse 金鑰** — 為 AI 報告流程提供可觀測性，選用。若不使用 Langfuse 可略過。

你隨時可以在 `.env` 檔案中新增或修改這些金鑰（執行 `spotify-mcp path` 可找到檔案位置）。

#### 啟動

```bash
uvx --from "spotify-analytics-mcp[dashboard]" spotify-mcp dashboard
```

#### 保持紀錄最新

從 Spotify API 同步最新的收聽紀錄（最多 50 筆）：

```bash
uvx --from spotify-analytics-mcp spotify-mcp sync
```

或在儀表板右上角點選「Sync」按鈕。

> 由於 Spotify API 最多只能取得最近 50 筆播放紀錄，sync 指令同樣有此限制。

---

### CLI 指令參考

| 指令 | 說明 |
|---|---|
| `spotify-mcp setup` | 互動式安裝精靈（已完成步驟自動略過） |
| `spotify-mcp serve` | 透過 stdio 啟動 MCP 伺服器（供 Claude Desktop 使用） |
| `spotify-mcp dashboard` | 啟動 Streamlit 儀表板（需要 `[dashboard]` 套件） |
| `spotify-mcp sync` | 從 Spotify API 同步最近的播放紀錄 |
| `spotify-mcp doctor` | 檢查環境就緒狀態（輸出 JSON 報告） |
| `spotify-mcp import-history` | 從 Spotify JSON 資料匯出檔匯入紀錄 |
| `spotify-mcp reauth` | 重新執行 OAuth 流程 |
| `spotify-mcp path` | 顯示設定檔與資料目錄位置 |
| `spotify-mcp --help` | 列出所有選項與指令 |
| `spotify-mcp --version` | 顯示已安裝的版本並結束 |

---

### 技術堆疊

| 層級 | 選擇 |
|---|---|
| MCP 框架 | FastMCP（Python MCP SDK） |
| LLM報告生成 | LangGraph（草稿 → 審閱流程） |
| 可觀測性 | Langfuse（選用） |
| 本地儲存 | SQLite（Spotify 紀錄 + 加密金鑰儲存） |
| 資料處理 | Polars + Pydantic |
| 儀表板 | Streamlit + Plotly |
| OAuth | Authorization Code with PKCE |

---

### 專案結構

```
packages/core/        # 共用函式庫：分析、資料庫、報告流程、spotify_client
packages/dataloader/  # 資料匯入（Polars + Pydantic）
apps/mcp/             # MCP 伺服器 + CLI + Streamlit 儀表板
data/                 # Spotify Listening Records JSON Data 範例樣板
```