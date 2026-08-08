# Shipping v1.0

> **這份是暫時的 —— v1.0 發完就刪掉。** 它是作業手冊（待辦、E2E、發版步驟），不是
> 架構文件。架構在 [`ARCHITECTURE.md`](ARCHITECTURE.md)，那份才是長期維護的。

一個別人可以下載、指向**他自己的** Cloudflare 帳號的 Windows 安裝檔。所以打包後的
app 不能假設機器上有 `uv`、Python 或 Node。

分支 `chore-python`，8 commits，`8b1e1f7..9b18168`。
（2026-08-07 squash 過，舊文件引用的 hash 都失效了。）

---

## 還沒做的

### 擋著 v1.0

- [ ] **乾淨機器的 E2E** —— 安裝 → 貼 Cloudflare token → deploy → 授權 → 匯入 → 重開。
  這是唯一真正的驗收測試，手冊在下面。
- [ ] **刪除報告的前端** (`9b18168`)。Worker 端已驗（`{"deleted":0}` / 400 / 401 都對）。
  要驗的是：刪掉 → **完全關掉 app 重開 → 它沒有回來**。純本機刪就是死在這一步。
- [ ] **Setup 的「Update the Worker」按鈕**。typecheck 和單元測試過了，沒實際按過。
  好驗：線上 Worker 已經有 DELETE 路由，成功的更新應該是 no-op。
- [ ] `WORKER_NAME` 首次寫入。現在的 config 還沒這個鍵，所以 Name 欄位這次仍可編輯，
  第一次更新後才會寫進去並鎖上。
- [ ] CI grep gate：`apps/tauri/src-tauri/src/` 內不得出現 `env!("CARGO_MANIFEST_DIR")`
  或 `Command::new`（dev-only 的 report spawn 例外）。
- [x] ~~README + 架構文件~~ 完成 2026-08-07：`docs/` 收成
      `ARCHITECTURE.md` + 這一份，README 重寫（英文、以安裝檔為主）。

### E2E 過了之後

- [ ] `windows-latest` NSIS smoke test：build → 靜默安裝 → 啟動 → 斷言 process 活著
  且寫出 `config.json`。那個 runner 沒有 Python 也沒有 `uv`，正是要的環境。
- [ ] **驗簽章私鑰的密碼**。`~/.tauri/spotify-analytics.key` 檔頭寫
  `rsign encrypted secret key`，但 rsign2 對空密碼也這樣寫，看不出來設過沒有。
  build 一次帶簽章就知道 —— 密碼忘了跟弄丟私鑰是同一件事。
- [ ] `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 進 GitHub secret（如果有密碼）。
      `TAURI_SIGNING_PRIVATE_KEY` 已完成（2026-08-04）。
- [ ] 第二台開發機：整個 `~/.tauri/` 複製過去，**不要重新產生**。keypair 綁的是 app
  不是機器；公鑰已編進 `tauri.conf.json`，第一份公開的 exe 出去後就鎖死了。

### 刻意不做（v1.0 之後或永遠）

| | |
|---|---|
| **Report / LangGraph** | v1 只有 dashboard。整個 Report 分頁 gate 在 `cfg.dev`（= 有設 `$SPOTIFY_CONFIG`），因為它到現在都還是 spawn `uv`。**在此之前那顆按鈕是無條件顯示的**，打包出去按下會噴 `failed to spawn 'uv'`。介面 `generate_report(...) -> markdown` 讓 PyInstaller sidecar 和 LangGraph.js 兩條路都還開著；下個版本決定(見下) |
| **MCP** | playback tools（`spotify_control.py`、`db_crud.py`、`spotify_facade.py`）還在讀一個沒人再寫的本機 `tokens.db`：程式在，但不會動，要等 MCP 改成跟 Worker 拿 token。之後那個 `tokens.db` 要刪掉 |
| **Keychain** | `TOKEN_ENCRYPT_KEY` 明文躺在 `config.json`。加密保護的是 D1 的靜態和傳輸，不是本機檔案存取 |
| **macOS** | `rfd` 在那邊需要 main thread，`lib.rs` 已標註 |
| **報告刪除的 tombstone** | 沒有 tombstone 表，所以第二台已拉過的機器本機會留著那筆。但它不會推回 D1（push 只送 `synced=0`），D1 是乾淨的。批次刪除、Python/MCP 的 delete 也同樣不做 |
| **export 覆蓋 API 的欄位合併** | 兩邊都是 `INSERT OR IGNORE`，先進來的贏。不影響任何圖表的**數字**，只影響舊列的 `ms_played` / `platform` / `skipped` 豐富度 |

---

## v1.01：要包 report 的時候（調查做完了，不要重查）

**先決定要不要串流。** 現在是一次性 spawn，argv 進、stdout 出，沒有協定 ——
所以溝通成本 < 總時間的 5%（報告本身要跑數十秒到數分鐘）。*真正的代價是發佈：要塞一個 Python runtime 進安裝檔（約 +150-250 MB），而且一次性 spawn **沒辦法邊生成邊顯示**。
要進度條就得逐行讀 stdout，或者直接走 JS。

實際需要的 runtime tree：langgraph + langchain-core + langchain +
langchain-google-genai + langsmith + langfuse（選用）+ pydantic + loguru + 內建sqlite3。
**numpy / pandas / polars 沒有任何模組 import**（全 repo grep 零命中），
`pyproject.toml:15,17` 那兩個 pin 是殘留的，不會進 bundle。

工作項目：

- `--add-data` 整棵 `spotify_core/db/sql/**` —— `queries.py:21` 用
  `importlib.resources` 讀，靜態分析抓不到。
- 預期要補 langchain/langgraph 的 hidden-import hook（它們大量動態 import）。
  grpc（langchain-google-genai → google-ai-generativelanguage）是最難搞的那個。
- `tauri.conf.json` 加 `bundle.externalBin`、Cargo 加 `tauri-plugin-shell`
  （兩個現在都沒有），然後刪掉 `lib.rs:17-24` 的 `REPORT_CMD` 和 `repo_root()`。
- subprocess 的介面不用改，sidecar 是 `REPORT_CMD` 的原地替換。
- 包好之後把 `App.vue` 的 `isDev` gate 拿掉。

---

## E2E 執行手冊

給「開一組全新的 D1 + Worker，從零跑到底」用的。**每一步的斷言才是重點，沒斷言的
步驟等於沒跑。**

### 先準備（缺東西中途要從頭來）

| 東西 | 怎麼拿 | 備註 |
|---|---|---|
| Cloudflare API token | dash.cloudflare.com → API Tokens → Create Custom Token，權限 `[Account][D1][Edit]` + `[Account][Workers Scripts][Edit]` | 用完即丟，不寫進 `config.json` |
| Stack 名稱 | 自己取，例如 `spotify-analytics-e2e` | **不要用日常那組**。Setup 頁的 Name 欄位就是它 |
| Spotify Client ID | developer.spotify.com 的 app | Redirect URI 必須**正好**是 `http://127.0.0.1:8888/callback`，不能用 `localhost` |
| Spotify export | 解壓後的資料夾，要含 `Streaming_History_Audio_*.json` | 沒有的話步驟 6-7 跳過，但那樣就驗不到 backfill |
| 乾淨環境 | 沒有 Python / uv / node 的 VM，或同一台的另一個 Windows 帳號 | 重點是 `%LOCALAPPDATA%` 和 `PATH` 都是新的 |

⚠️ 乾淨環境**不能設 `SPOTIFY_CONFIG`**。設了就會讀 repo 裡的 dev config，等於沒在驗打包路徑。

⚠️ **隔離測試，碰不到你正式那組。** 測試用一個**新的 stack name**（例如 `spotify-analytics-e2e`）＋**另一個 Spotify Client ID**（dashboard 另開一個 app）：D1 是按名字分開的獨立資料庫，正式的 D1／Worker 一個 byte 都不會被動到，正式 cron 測試期間照常每小時收資料、**不會有 history gap**。因為在隔離環境（另一個帳號／VM／config）測，正式 `config.json` 從頭沒被改，測完刪掉測試的 Worker＋D1 即可，**沒有東西要切回來**。

### 做出安裝檔

```bash
cd apps/tauri
npm test                  # 49 passed
npm run tauri build       # 5-15 分鐘
```

產物在 `apps/tauri/src-tauri/target/release/bundle/nsis/`，拿
`spotify-analytics_0.1.0_x64-setup.exe` 去乾淨環境。`*.nsis.zip` 和 `.sig` 是
updater 用的，E2E 不需要。沒設 `TAURI_SIGNING_PRIVATE_KEY` 這步會因為
`createUpdaterArtifacts: true` 而失敗或跳過簽章；E2E 階段可以不管。

### 跑

1. **安裝 → 啟動**
   - 只出現 Setup 視窗，dashboard 不該出現
   - 斷言：`%APPDATA%\com.<username>.spotify-analytics\config.json` 生出來了
     （Rust 寫的，證明啟動路徑沒有 Python）

2. **Spotify Client ID** → Save and continue

3. **Cloud sync**：貼 token + Name → Deploy
   - 斷言：Cloudflare dashboard 看得到 D1、Worker script、以及 **Cron Trigger `7 * * * *`**
     （三個都要看 —— schedule 是分開一次 API call 上去的，最容易掉）
   - 斷言：log pane 沒印出 token 或曲名
   - 斷言：`config.json` 有 `WORKER_NAME`，回 Setup 時 Name 欄位是唯讀的
   - ⚠️ 新路由上線後 404 約一分鐘是 edge 傳播，不是失敗

4. **Authorize Spotify** → 瀏覽器授權 → 跳回 app
   - 斷言：`curl -H "Authorization: Bearer <token>" <worker_url>/api/tokens` 有一列
   - 斷言：本機不該有 `tokens.db`

5. **抓最新 50 筆**（Setup 頁的 sync）
   - 斷言：dashboard 開得起來、有資料。**記下 All time 的 plays 數字**

6. **匯入 export 資料夾**
   - 斷言：`GET /api/tracks/count` 跳到幾萬。本機還是舊的少數，**這是預期的**

7. **完全關掉 app，重開** ← 驗 backfill (`fe4ee3d`)
   - 斷言：All time 跟步驟 6 的 D1 count 一致
   - 斷言：console 有 `sync: local N rows vs D1 M — backfilling from the epoch`
   - **這步失敗就是 backfill 沒生效，其他都不用看了**

8. **再重開一次**
   - 斷言：console 是 `inserted 0`、沒有 backfill 訊息、開機不卡、All time 不變

9. **刪一份報告 → 關掉重開** ← 驗 delete (`9b18168`)
   - 斷言：它沒有回來

10. **等一個整點過 7 分**（或 dashboard 手動觸發 cron）
    - 斷言：D1 count 增加 → 重開 app → 本機跟上

**跑完清乾淨**：E2E 的 Worker 留著會繼續每小時打 Spotify API。手動刪掉 Worker + D1，
或留著當測試環境 —— 但要記得它在跑。

---

## Release 步驟

```bash
# 版號：tauri.conf.json 的 version 是唯一來源。
# updater 靠它比對，忘了改 = 使用者永遠收不到更新。
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content ~/.tauri/spotify-analytics.key -Raw
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "..."
cd apps/tauri; npm run tauri build
```

上傳到 GitHub Release 三個檔案：`_x64-setup.exe`（使用者下載）、
`_x64-setup.nsis.zip`（updater 抓的）、`latest.json`（updater 的索引，**必須手寫或用
tauri-action 產**）。

`tauri.conf.json` 的 endpoint 是
`https://github.com/wcnoname5/spotify-ai-analytics/releases/latest/download/latest.json`，
所以 **`latest.json` 沒上傳 = updater 靜默失效**（不報錯，只是永遠說沒有更新）：

```json
{
  "version": "0.1.1",
  "notes": "...",
  "pub_date": "2026-08-04T00:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<.nsis.zip.sig 的內容>",
      "url": "https://github.com/.../spotify-analytics_0.1.1_x64-setup.nsis.zip"
    }
  }
}
```

---

## 不要再破壞的規則

踩過的坑，每一條都是實際發生過的 bug。

- **`listening_history.id` 只能有一份實作。** 曾經有兩份，cron 和 export 匯入的同一次
  播放會在每張圖裡被算兩次。現在在 `packages/shared-ts/`。
- **分頁游標是 `(played_at, id)`，不是 `played_at`。** 同一秒的兩筆跨頁會被**永久**跳過。
- **報告刪除必須先刪 D1。** `syncReports` 的 pull 游標是 `MAX(generated_at)`，只刪本機
  會讓游標倒退，下次開機直接從 D1 拉回來。
- **`syncOnStartup` 開機要比對 row count。** 游標只會往後拉，所以比本機最新還舊的列
  永遠拉不下來 —— 而「先抓最新 50 筆、幾天後 export 才到」正好會產生那種資料。
  local 少就從 EPOCH 全掃（`INSERT OR IGNORE` 讓它冪等）。
- **Deploy 的 Name 對不上不會報錯**，會默默建出第二個 Worker + 空 D1。所以更新時
  `WORKER_NAME` 唯讀。
- **token row 不能寫死 `"default"`**，會跟 `SPOTIFY_USER_ID` 不一致，症狀是 cron sync
  安靜地找不到 token。
- **`capabilities/setup.json` 要跟著 Setup 視窗的功能加。** 少了就是 runtime 被擋。
- **測試要隔離 config 目錄。** 曾經有六個測試檔在讀開發者的真實 config。

---

## 附錄：已完成的階段

| Phase | 做了什麼 |
|---|---|
| **0** `8b1e1f7` | 移除沒用的依賴。AGENTS.md 和 copilot-instructions 是 CLAUDE.md 的漂移副本 → 改成指標 |
| **1** `b546c37` | **Rust 擁有 config**（JSON）。`get_config` 從 1706 ms 的 process spawn 變成讀檔，`doctor` 那次 spawn 也沒了 |
| **2** `84826c1`+`1861a4f` | **App 擁有 setup**：OAuth（PKCE in TS + Rust loopback）、history import、sync。刪掉 `wizard/`（9 模組）、`seed.py`、`env_file.py`、`packages/dataloader` 和 11 個測試檔 |
| **3** `b751c3a` | **Deploy 是 Rust → Cloudflare REST**。Worker 由 `build.rs` 打包（esbuild，17 kB）並 `include_str!` 進 binary。runtime 不需要 node/npx/wrangler |
| **4** `dc21fba` | 本機 SQLite schema 版本化（`PRAGMA user_version`）、有上限的分頁 sync、updater 簽章金鑰 |
| `fe4ee3d` | 本機快取 backfill；修好 Tracing 步驟卡住 |
| `ff50962` | Past reports 改成卡片 grid |
| `9b18168` | 刪除報告；Setup 可以更新既有 Worker |

**site-packages: 657 MB → 203 MB.** Python 只剩 LangGraph 報告生成和 MCP server。

三件還在成立的架構事實：

- **Spotify token 不落地。** OAuth 加密（Fernet）後直接 POST 進 D1，只有 Worker cron
  會解密。這殺掉了整類 refresh-token 輪替不一致的 bug，也殺掉了 `tokens.db`。
- **跨邊界的規則只能有一份實作。** `packages/shared-ts/`（Fernet、PKCE、row id、export
  解析）同時被 Worker 和前端 import；`db/sql/migrations/` 是 D1、本機快取和 Python
  共用的唯一 schema 來源。
- **Setup 有硬性順序**：`client_id → worker → oauth → history`。沒有 Worker 就不能授權，
  因為 token 沒有別的地方可以放。
