# Spotify token lineage：cron 為什麼會 crash，以及怎麼安全地重新授權

**Date:** 2026-07-21
**Status:** 診斷已確認；step 2 實機驗證因故暫緩
**相關:** roadmap section 2、`docs/superpowers/specs/2026-07-20-tauri-setup-gui-design.md`

## Context

Setup GUI 的 DB init 修正與六步 wizard 已完成（229 tests / vue-tsc / cargo check 全過；fresh env 實跑確認 `tokens.db`、`history.db` 由 promptless 步驟自建）。唯一還沒實機驗過的是 wizard step 2 的 Authorize 按鈕——因為擔心重新授權會弄壞 D1 裡正在被 Worker cron 使用的 token。

文件目的是釐清Spotify Authentication 怎麼 crash cloudfalre 的 cron

---

## 診斷：不是 PKCE，也不是「兩把 Fernet key」

**不是 PKCE。** `packages/core/spotify_core/spotify_client/auth.py` 全檔沒有 Fernet；`code_verifier` 每次現產、用完即丟、從不落地。PKCE 只是換 token 的握手，跟加密儲存無關。

**不是兩把 key。** 目前是兩組各自自洽的 (key, ciphertext)：

| 環境 | 金鑰 | 密文 |
|---|---|---|
| 測試 (fresh env) | `scratchpad/fresh/.env` 的 `TOKEN_ENCRYPT_KEY` | `scratchpad/fresh/data/tokens.db` |
| prod | Worker secret | D1 的 `spotify_tokens` |

兩組永遠不會相遇。唯一會把本地 token 送進 D1 的是 `scripts/seed_d1.py`（`seed_tokens()` → `worker.post_tokens`），而它需要 `WORKER_URL` + `WORKER_AUTH_TOKEN` 兩個環境變數，測試環境的 `.env` 兩個都沒有。**GUI 沒有任何路徑能寫 D1。**

**真正的機制：一顆 refresh token、兩個持有者。**

Spotify 的 PKCE refresh 會回一顆新的 refresh token 並讓舊的失效，程式兩邊都照做：

- 本地：`packages/core/spotify_core/spotify_client/client.py:113-119`
- Worker：`worker/src/sync.ts:51-58`（每次 refresh 都 upsert 回 D1）

所以誰第二個 refresh，誰就拿到 400 `invalid_grant`。這個狀態**只有在 token 被複製過**才會出現——也就是跑了 `seed_d1.py --tokens-only`。先前那次 sync-test 事故正是這個形狀，**不是重新授權造成的**。

**推論：Worker 每小時改寫 D1 的 refresh token，所以任何本地副本一小時內就過期。**「先留一份備份以防萬一」在這個架構下無效，別做。

---

## 安全做法：測試環境用第二個 Spotify app

Spotify 的 token lineage 是 per-(user, client_id)。換一個 client_id，新舊兩條線在 Spotify 端就沒有任何關係——不需要知道「重新授權會不會讓舊 token 失效」這個問題的答案，因為它從構造上就不適用。

1. https://developer.spotify.com/dashboard 建第二個 app
2. Redirect URI 填 `http://127.0.0.1:8888/callback`（`localhost` 會被拒，Spotify 2025-11 起）
3. 複製新的 Client ID
4. 測試環境的 wizard step 1 貼**新的** client ID（若已貼舊的，改 `.env` 的 `SPOTIFY_CLIENT_ID` 後重開 app）
5. 按 Authorize Spotify，走完瀏覽器流程

**Worker secret 完全不用動**，prod 的 key 和 token 原封不動，cron 不受影響。

成功信號：測試環境 `data/tokens.db` 的 `spotify_tokens` 出現一列（看時間戳即可，不必解密），且 wizard 自動前進到 `Step 3 of 6`。

### 現況：此路暫時不通

**2026-07-21：Spotify 不讓這個帳號再建第二個 app**，所以上面的做法目前無法執行。決定是 **step 2 先不驗**：

- step 2 spawn 的 `reauth` 是既有指令，本次唯一改動是加了一行 `init_tokens_db`，而那行已被 `tests/mcp/test_cli_setup.py::test_reauth_initializes_tokens_db_before_browser` 覆蓋（把修正抽掉會紅）
- 真正未驗的只剩 Tauri spawn 那層，而同一條路（`runStep` → `run_setup_step` → buffered 輸出）已經被 import / sync 兩顆按鈕驗過
- 換得的是不必賭 prod cron

解除條件：拿到第二個 client_id（換一個 Spotify 帳號也行），或 prod token 因其他原因本來就要重新授權——那時順手驗。

---

## Break-glass：真的需要幫 prod 重新授權／換 key 時

只在 prod token 已經壞掉、或確定要輪替加密金鑰時才做。順序有意義：D1 的 ciphertext 和 Worker secret 必須配對，中間有一段兩者不一致的空窗。

cron 是 `7 * * * *`，所以**在整點過 8 分後動手**，可拿到約 55 分鐘餘裕。

```bash
# 1. 本地重新授權（用 prod 的 client_id 和 prod 的 TOKEN_ENCRYPT_KEY）
uv run spotify-mcp reauth

# 2. 推新的加密 token row 進 D1
WORKER_URL=... WORKER_AUTH_TOKEN=... uv run python scripts/seed_d1.py --force --tokens-only

# 3. 只有在 key 也換了才需要這步（沿用舊 key 就跳過）
cd worker && npx wrangler secret put TOKEN_ENCRYPT_KEY
```

若 key 沒換（**建議沿用**），第 3 步免了，空窗也不存在。第 3 步存在時，**先做 2 再做 3**：中間 cron 若剛好跑，它拿舊 key 解新 ciphertext 會失敗一次，下一輪自動恢復；反序則是壞到你補完為止。

驗證 prod 沒事：`wrangler tail` 觀察下一次 `7 * * * *` cron，或隔一小時比對 D1 的 `MAX(played_at)` 有沒有前進。
