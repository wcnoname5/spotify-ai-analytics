# Shipping v1.0

> **這份是暫時的 —— v1.0 發完就刪掉。** 它是作業手冊（待辦、E2E、發版步驟），不是
> 架構文件。架構在 [`ARCHITECTURE.md`](ARCHITECTURE.md)，那份才是長期維護的。

一個別人可以下載、指向**他自己的** Cloudflare 帳號的 Windows 安裝檔。所以打包後的
app 不能假設機器上有 `uv`、Python 或 Node。

刻意不做的事和不能破壞的規則都在 `ARCHITECTURE.md`，這裡不重複。

---

## 還沒做的

### 擋著 v1.0

- [ ] **乾淨機器的 E2E** —— 安裝 → 貼 Cloudflare token → deploy → 授權 → 匯入 → 重開。
  這是唯一真正的驗收測試，手冊在下面。
- [ ] **刪除報告的前端** (`9b18168`)。Worker 端已驗（`{"deleted":0}` / 400 / 401 都對）。
  要驗的是：刪掉 → **完全關掉 app 重開 → 它沒有回來**。純本機刪就是死在這一步。
- [ ] **Setup 的「Update the Worker」按鈕**。typecheck 和單元測試過了，沒實際按過。
  好驗：線上 Worker 已經有 DELETE 路由，成功的更新應該是 no-op。
- [x] ~~`WORKER_NAME` 首次寫入~~ 每次 deploy 都會寫（`lib.rs`），E2E 步驟 3 驗。
- [ ] **Report 分頁對所有人顯示**（2026-10-20 拿掉 `isDev` gate）。打包版按下產生報告
  會噴 `failed to spawn 'uv'`，發 v1.0 前要嘛包好 report，要嘛接受這個錯誤訊息。
- [ ] **Updater 沒接上**：`tauri-plugin-updater` 有註冊，但沒有任何地方呼叫 `check()`，
  已安裝的版本永遠不會更新。發 v1.0 前接上，否則 v1.0 使用者只能手動重裝。
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

---

## v1.01：要包 report 的時候（調查做完了，不要重查）

**先決定要不要串流。** 現在是一次性 spawn，argv 進、stdout 出，沒有協定 ——
所以溝通成本 < 總時間的 5%（報告本身要跑數十秒到數分鐘）。*真正的代價是發佈：要塞一個 Python runtime 進安裝檔（約 +150-250 MB），而且一次性 spawn **沒辦法邊生成邊顯示**。
要進度條就得逐行讀 stdout，或者直接走 JS。

實際需要的 runtime tree：langgraph + langchain-core + langchain +
langchain-google-genai + langsmith + langfuse（選用）+ pydantic + loguru + 內建sqlite3。
**numpy / pandas / polars 沒有任何模組 import**，不會進 bundle。

工作項目：

- `--add-data` 整棵 `spotify_core/db/sql/**` —— `queries.py:21` 用
  `importlib.resources` 讀，靜態分析抓不到。
- 預期要補 langchain/langgraph 的 hidden-import hook（它們大量動態 import）。
  grpc（langchain-google-genai → google-ai-generativelanguage）是最難搞的那個。
- `tauri.conf.json` 加 `bundle.externalBin`、Cargo 加 `tauri-plugin-shell`
  （兩個現在都沒有），然後刪掉 `lib.rs` 的 `REPORT_CMD` 和 `repo_root()`。
- subprocess 的介面不用改，sidecar 是 `REPORT_CMD` 的原地替換。

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
npm test                  # 全過
npm run tauri build       # 5-15 分鐘
```

產物在 `apps/tauri/src-tauri/target/release/bundle/nsis/`，拿
`spotify-analytics_0.1.0_x64-setup.exe` 去乾淨環境。`*.nsis.zip` 和 `.sig` 是
updater 用的，E2E 不需要。沒設 `TAURI_SIGNING_PRIVATE_KEY` 這步會因為
`createUpdaterArtifacts: true` 而失敗或跳過簽章；E2E 階段可以不管。

### 跑

1. **安裝 → 啟動**
   - 只出現 Setup 視窗，dashboard 不該出現
   - 斷言：`%LOCALAPPDATA%\spotify-mcp\spotify-mcp\config.json` 生出來了
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

