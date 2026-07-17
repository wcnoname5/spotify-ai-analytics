# 個人 Spotify Dashboard 專案規格草稿

## 1. 專案目標

打造一個本機桌面 App，讓自己能簡單瀏覽個人 Spotify 聽歌數據，並透過 LLM 產生聽歌報告。資料不對外公開，僅限本人存取。

---

## 2. 技術棧總覽

| 層級 | 技術 | 說明 |
|---|---|---|
| 遠端資料庫 | Cloudflare D1 | 聆聽紀錄 + Spotify token 儲存 |
| 資料同步 (雲) | GitHub Actions (cron, 每小時) + Python | 呼叫 Spotify API，寫入 D1 |
| API Gateway | Cloudflare Worker (TypeScript) | D1 唯一存取入口，需 Bearer token 驗證 |
| 本地快取 DB | SQLite | App 啟動時從 Worker API 增量同步 |
| 報告生成 | Python + LangChain | 讀本地 SQLite，產生報告/對話 |
| （選用）本地工具介面 | MCP server (stdio) | 包裝本地 SQLite，供 local LLM tool call |
| 前端 | TypeScript + Vue | Dashboard（Plotly 圖表 + filter）+ 對話介面 |
| 對話邏輯 | ReAct pattern | 前端驅動 agent loop |
| App 封裝 | Tauri | 打包成 .exe / .app，單一安裝檔 |

---

## 3. 資料流架構

```
[Spotify API]
     │ 每小時
     ▼
[Worker cron (scheduled(), TS)] ──write──▶ [Cloudflare D1]
                                                │
                                     [Cloudflare Worker API]
                                       (Bearer token 驗證)
                                                │
                        ┌───────────────────────┴───────────────────────┐
                        ▼                                               ▼
              App 啟動時：增量同步                            Dashboard 查詢：即時打 API
                        │                                               │
                        ▼                                               ▼
              [本地 SQLite Cache]                              [Vue Dashboard 圖表]
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
  [Python + LangChain 報告生成]   [(選用) MCP Server stdio]
          │                           │
          ▼                           ▼
   [報告輸出]          [連到Claude Code去]
```

**關鍵原則：D1 是唯一 source of truth，本地 SQLite 只是同步快取（cache），不獨立寫入。**

---

## 4. 各模組職責

### 4.1 雲端資料層
- **D1 Tables**：
  - `listening_history`：track、artist、played_at、duration 等
  - `spotify_tokens`：access/refresh token（加密儲存）
- **GitHub Actions**：每小時觸發 Python script → 呼叫 Spotify API → upsert 進 D1
- **Worker API**（TS）：
  - `GET /api/tracks?since=<timestamp>` — 增量拉取
  - `GET /api/tracks?from=&to=&filter=` — dashboard 用聚合查詢
  - Middleware：檢查 `Authorization: Bearer <AUTH_TOKEN>`，token 存 Worker secret

### 4.2 本地同步
- 小型腳本（TS 或 Python 皆可），App 啟動時執行：
  1. 讀本地 `meta` table 取得 `last_sync_at`
  2. 打 `GET /api/tracks?since=last_sync_at`
  3. UPSERT 進本地 SQLite
  4. 更新 `last_sync_at`

### 4.3 報告生成（Python + LangChain）
- 讀本地 SQLite 作為資料來源
- 產出：定期摘要報告(週報/月報)
- 執行方式：Tauri 透過 `child_process` / sidecar 呼叫 Python script，或起一個本地 Python 服務（如 FastAPI）供前端呼叫

### 4.4 （選用）MCP Server
- 包裝本地 SQLite 為 MCP resource/tool（stdio transport）
- 供 LangChain agent 以標準化方式 query，取代直接寫死 SQL in prompt
- 可用現成 `mcp-server-sqlite` 減少自建成本

### 4.5 前端（Vue + TS）
- **Dashboard 頁**：filter 元件 → 打 Worker API（非本地）→ Plotly 渲染
- **報告頁**：按鈕觸發報告生成 render 每週/月報告，呼叫本地 Python service (langgraph)

### 4.6 App 封裝（Tauri）
- Rust 殼僅負責視窗、生命週期管理，不寫業務邏輯
- 用 sidecar 綁定 Python 執行檔（`pyinstaller` 打包後嵌入）
- Token（Worker AUTH_TOKEN）存於 OS keychain，不寫死在前端 bundle 內

---

## 5. 待確認/開放問題

- [ ] Python report service 要常駐（本地小型 server）還是每次呼叫都 spawn 新 process？ (每次呼叫再spawn就好。)
- [ ] 本地同步是否需要處理「App 開著時遠端又有新 cron 寫入」的情境（可加「同步後 N 分鐘自動再同步」機制）
- [ ] MCP server 等 v1 功能穩定後再加
- [ ] Tauri sidecar 打包 Python 執行檔的跨平台體積/相依性測試（尤其 LangChain 相依套件較多）

---

## 6. 建議實作順序

1. Worker API + D1 schema 定案，含 auth middleware
2. Worker cron（scheduled() handler）上線，驗證資料持續寫入
3. 本地同步腳本（增量 sync 邏輯）
4. Python + LangChain 報告生成，先跑通本地 SQLite → 報告輸出
5. Vue dashboard 基本圖表 + filter（先在瀏覽器測試，不急著包 Tauri）
6. ReAct 對話框接上報告生成邏輯
7. Tauri 封裝整合，處理 sidecar + token 安全存放
8. （選用）MCP server 抽換掉直接 SQL query 的部分
