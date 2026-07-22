# Setup wizard UX re-ordering + safe end-to-end testing

**Date:** 2026-07-22
**Status: implemented and verified.** Findings A–D are fixed, Env A was driven end-to-end against a
second Spotify account, and Env B ran a real Cloudflare deploy on a disposable stack (since torn
down; prod untouched). Kept as the record of *why* the wizard is ordered the way it is and how to
re-run the isolated testing — the runbooks below are still current.

Two things this doc gives you: (1) a proposed re-ordering of the GUI setup wizard, with the
dependency graph and concrete UX findings, so the ordering can be judged before it's built; and
(2) a reproducible, isolated way to drive the whole setup end-to-end with **zero risk** to the
live prod D1 or the prod Spotify token. A condensed reference (create-sequence, DB model, token
lineage, deploy) is in the appendix.

---

## Part 1 — Wizard step re-ordering

### The true dependency graph (what *must* precede what)

```
config/data dirs ─┐
SPOTIFY_CLIENT_ID ─┼─► OAuth (encrypted token) ─► "Fetch last 50 plays"
TOKEN_ENCRYPT_KEY ─┘                                (needs a live token)

history.db ─► JSON import   ← needs NOTHING but the export file (no client_id, no OAuth)

LLM key    ─► AI reports    ← needed ONLY for reports, nothing else
Worker/D1  ─► durable history + hourly auto-sync   ← optional to run, but see Finding C
```

Only three hard edges exist: `client_id` + Fernet key must precede OAuth; OAuth must precede the
"fetch 50" fallback. **Everything else is UX choice, not a constraint.** JSON import is fully
independent of OAuth (`apps/mcp/spotify_mcp/wizard/history_import.py:114-126`).

### Current order and its UX problems

Current: `client_id → oauth → history → llm → tracing → worker` (`SetupPage.vue` `ORDER`).
Skippable today: history, tracing, worker. **Not** skippable: client_id, **oauth**, **llm**.

- **Finding A — the LLM step traps you.** `llm` has no Skip button and only clears when a key is
  entered (`stepDone.llm = hasLlm`). A user who only wants the dashboard **cannot finish the
  wizard** without an LLM key — yet a key is needed *only* for AI reports. → make LLM Skippable.
- **Finding B — the breakable step is first, before any payoff.** OAuth (browser, port 8888,
  redirect URI — and the one step never verified end-to-end) is mandatory at position 2, before the
  user sees a single chart. A user *with their export* could populate the dashboard via JSON import
  with no OAuth at all.
- **Finding C — the durability trap is buried and under-sold.** "Cloud sync" is last and framed as
  optional, but it's what makes imported history durable. Local `history.db` is a disposable mirror
  of D1 (Appendix §2): imported JSON that never reaches D1 is silently lost on any cache rebuild.
- **Finding D — the encryption key is invisible.** `TOKEN_ENCRYPT_KEY` auto-generates silently; the
  "back up this key or your tokens die" warning shows only in `showAll`, never in the wizard.

### Proposed re-order (modest — moves one step, reframes copy, fixes skips)

```
Group A · Connect Spotify        1. Client ID        2. Authorize
Group B · Your data (pick ≥1)    3. Listening history  (JSON import  |  fetch last 50)
Group C · Keep it live           4. Cloud sync   ← promoted ahead of LLM; reframed "recommended"
Group D · AI reports (optional)  5. LLM provider (now Skippable)   6. Tracing
```

Change vs current: **move Cloud (`worker`) ahead of `llm`/`tracing`**, **make `llm` Skippable**,
and regroup into four labelled phases so required core (A+B) is visually separate from optional (D).
Small diff to `SetupPage.vue` `ORDER` + one Skip button + copy; not a rewrite.

| Step | User action | Why here / notes |
|------|-------------|------------------|
| 1 Client ID | Opens dashboard, pastes Client ID | Anchor; Fernet key + DBs auto-created behind this. **Add a "your encryption key was created — back up `<.env>`" notice here** (fixes Finding D) |
| 2 Authorize | Browser round-trip | Mandatory for ongoing/live sync. The risk point (Finding B) — see open question |
| 3 History | "I have my export" → folder pick (no auth needed) **or** "Not yet" → fetch 50 (needs step 2) | First real payoff — dashboard populates. If Cloud (4) is configured, offer **"Back up to cloud"** right after import (fixes Finding C) |
| 4 Cloud sync | Paste WORKER_URL/token or run deploy | Promoted + reframed: "recommended — keeps your history safe and auto-updating hourly." Skippable, but sold as the durable path |
| 5 LLM | Paste Gemini/OpenAI key | **Now Skippable** (Finding A). Only gates reports |
| 6 Tracing | Optional | Unchanged |

**Resolved 2026-07-22 — keep OAuth first.** Env A run: every button worked, OAuth included, so
Finding B's "the breakable step gates the first payoff" premise didn't hold. Original question kept
below in case OAuth turns flaky on someone else's machine.

**Open UX question (decide after seeing it running):** should JSON import (step 3) be allowed
*before* OAuth, so a user with their export sees value even if OAuth is flaky?
- *Keep OAuth first (default):* simpler — step 3's "fetch 50" always works, app is complete for
  ongoing sync. Cost: the breakable step gates the first payoff.
- *Data-first (history before OAuth):* value without the risky step; OAuth becomes "connect for
  ongoing updates." Cost: "fetch 50" is disabled until you go back and authorize.

Recommendation: **keep OAuth first + make everything past step 3 skippable**, so a user can always
reach a populated dashboard and stop.

---

## Part 2 — Safe, reproducible end-to-end test

### The three independent risks to prod (and how each is neutralised)

| Risk | What triggers it | Isolation |
|------|------------------|-----------|
| Overwrite prod local `.env` / DBs | Running against your real config dir | Set `SPOTIFY_MCP_CONFIG_DIR` + `SPOTIFY_MCP_DATA_DIR` to a scratch dir → separate `.env`, `history.db`, `tokens.db` |
| Strand the **prod Spotify token** (`invalid_grant`) | Authorizing with the **prod `client_id`** in any env | Use a **second Spotify account's app** (different `client_id`) — different `(user, client_id)` lineage, cannot touch prod's refresh token |
| Write to **prod D1** | A scratch `.env` whose `WORKER_URL`/token points at the prod Worker (seed/push) | Leave the Worker **unset** (Env A), or point at a **separate test Worker+D1** (Env B). The app's track sync is pull-only, but `seed_d1.py` pushes — never aim it at prod |

**Golden rule:** in a scratch env, never paste the **prod client_id** and never set `WORKER_URL`
to the **prod Worker**. Those are the only two actions that reach prod.

### Which env to create

- **Env A — local-only (create this first; it unblocks the UX testing).** Cost: one free second
  Spotify account. No Cloudflare resources. Covers wizard steps 1,2,3,5,6, local DB creation, JSON
  import, dashboard, and AI reports. The Cloud step you simply **Skip**. Zero prod risk by
  construction (scratch dirs + second Spotify account + no Worker).
- **Env B — full parallel stack (only to exercise Cloud/cron/seed).** Env A **plus** a separate test
  Worker + test D1. Since 2026-07-22 this is just the Cloud card's **Name** field: set it to
  `spotify-analytics-test` and deploy. `cloud deploy` renders a throwaway wrangler config per run
  and never writes `worker/wrangler.toml`, so a test deploy leaves nothing behind that a later prod
  deploy could pick up. A second Cloudflare account is now optional belt-and-braces, not the
  isolation mechanism.

### Env A runbook (from your own terminal)

```bash
# 0. one-time: second Spotify account -> developer.spotify.com/dashboard -> create app
#    redirect URI  http://127.0.0.1:8888/callback   -> copy the NEW Client ID

# 1. pick a scratch root and WIPE it (leftover DBs make the wizard skip to the wrong step)
TEST=/d/spotify-test/fresh
rm -rf "$TEST"

# 2. isolate config + data into the scratch root
export SPOTIFY_MCP_CONFIG_DIR="$TEST"
export SPOTIFY_MCP_DATA_DIR="$TEST/data"

# 3. launch the app FROM THIS TERMINAL (a backgrounded shell makes the exe exit immediately)
cd apps/tauri && npm run tauri dev
```

<details><summary>PowerShell equivalent</summary>

```powershell
# 0. one-time: second Spotify account -> developer.spotify.com/dashboard -> create app
#    redirect URI  http://127.0.0.1:8888/callback   -> copy the NEW Client ID

# 1. pick a scratch root and WIPE it (leftover DBs make the wizard skip to the wrong step)
$TEST = "D:\spotify-test\fresh"
Remove-Item $TEST -Recurse -Force -ErrorAction SilentlyContinue

# 2. isolate config + data into the scratch root
$env:SPOTIFY_MCP_CONFIG_DIR = $TEST
$env:SPOTIFY_MCP_DATA_DIR   = "$TEST\data"

# 3. launch the app FROM THIS TERMINAL (a backgrounded shell makes the exe exit immediately)
cd apps\tauri
npm run tauri dev
```
</details>

Per-step UX verification checklist (tick while clicking — this is the feedback pass):

1. **Fresh launch** → the Setup window pops on its own (unconfigured); dashboard behind shows the
   offline banner. *(Also verifies the gear → separate-window change.)*
2. **Step 1 Client ID** → paste the **second account's** ID, Save → advances to step 2. Confirm a
   "back up your encryption key" notice appears (added 2026-07-22 — Finding D).
3. **Step 2 Authorize** → browser opens, log in as the **second account**, consent → returns;
   `"$TEST\data\tokens.db"` gains a `spotify_tokens` row (check the file timestamp); wizard → step 3.
4. **Step 3 History** → point the folder picker at a copy of your `Streaming_History_Audio_*.json`
   → dashboard fills. Re-run the import → confirm "duplicates skipped" (idempotent, harmless). Try
   "fetch last 50" → confirm it needs the token from step 2.
5. **Step 4 Cloud** → Skip (Env A has no Worker). **Step 5 LLM** → **Skip without a key**
   (added 2026-07-22 — Finding A) → **Step 6 Tracing** → Skip → "Setup complete".
6. **Reset for the next run:** rerun step 1's `Remove-Item`. Each run must start from an empty dir.

Everything above writes only under `D:\spotify-test\fresh`. Your real `.env`, `history.db`, prod
D1, and prod cron are untouched.

### Env B addendum (only to test Cloud) — superseded by the GUI, kept for the reasoning

All of the manual work below is now one field and one button: in the Cloud card set **Name** to
something like `spotify-analytics-test` and press Deploy. `cloud deploy` creates the D1, applies
migrations, deploys the Worker, sets all three secrets, writes `WORKER_URL`/`WORKER_AUTH_TOKEN` to
the *scratch* `.env`, and seeds — and it renders a throwaway wrangler config per run, so a test
deploy cannot leave a `database_id` behind for a later prod deploy. Teardown is
`wrangler delete --name <name>-worker --force` + `wrangler d1 delete <name> -y`.

The original manual recipe, for when you need to reason about what the button does:

> After Env A works: create the test Worker/D1, then in the scratch `.env` set
> `WORKER_URL`/`WORKER_AUTH_TOKEN` to the **test** Worker, give that Worker its secrets
> (`AUTH_TOKEN` new, `SPOTIFY_CLIENT_ID` = second account, `TOKEN_ENCRYPT_KEY` = the **scratch**
> `.env`'s key), and seed. Verify the app pulls from the test D1 and the test cron ticks
> (`wrangler tail`). Never reuse prod's Worker URL or D1 name.

---

## Appendix — condensed reference

**§1 Create-sequence (local).** `run_wizard()`: ensure_dirs → `SPOTIFY_CLIENT_ID` (.env) → Fernet
key (.env, auto, never overwrites) → `init_history_db` + `init_tokens_db` (two files) → OAuth (PKCE
browser → encrypted `spotify_tokens` row) → history import/sync (`listening_history` + `sync_state`)
→ optional LLM/tracing → optional claude_desktop config. The GUI drives the same via promptless
subcommands (`config set/keygen`, `reauth`, `import-history --from`, `sync`), each self-initing its DB.

**§2 DB model.** `history.db` = `listening_history` (PK `id` = sha1(`uri:played_at`)) + `sync_state`
(cursor) + `reports`. `tokens.db` = `spotify_tokens` (tokens Fernet-encrypted, `expires_at`
plaintext). The app reads `history.db` **only**; it never opens `tokens.db`. Local SQLite is a
**pull-only disposable mirror** of D1 (`lib/sync.ts` `INSERT OR IGNORE` from
`/api/tracks?since=MAX(played_at)`); reports are the lone push-then-pull exception. All track
inserts (local import + Worker `POST /api/tracks`) are `INSERT OR IGNORE` on the content-hash PK →
**idempotent, never corrupt existing data in either DB** — this is why re-import / re-seed is always
safe. (Corollary, and Finding C: safe ≠ durable — a local import that never reaches D1 is lost on
cache rebuild.)

**§3 Cloud deploy (`spotify-mcp cloud deploy`, was `scripts/setup_cloud.sh` until 2026-07-22).**
Requires client_id + Fernet key to already exist (the wizard's job; it never prompts) → `d1 create`
→ resolve id into a **throwaway** wrangler config → `d1 migrations apply --remote` → **`wrangler
deploy` (cron `7 * * * *` goes live here)** → `secret put
AUTH_TOKEN/SPOTIFY_CLIENT_ID/TOKEN_ENCRYPT_KEY` (`SPOTIFY_USER_ID` defaults `"default"`) → write
`WORKER_*` back to .env → seed (retry loop for secret propagation, pushes local tokens + history).
The Bearer token is **reused** across runs; `--rotate` is the opt-in, and it 401s every other
machine. Cloudflare secrets are write-only, so `.env` holds the only readable copy.

**§4 Token lineage — two independent things.** (A) *Spotify PKCE rotation:* each refresh may return a
new refresh token and revoke the old; two holders of one token copy → the second refresher gets
**HTTP 400 `invalid_grant`**. This fragility exists only because there are two refreshers (local
client + Worker cron); the Worker is the single live refresher, and local reads pull from D1.
(B) *Our Fernet encryption:* `TOKEN_ENCRYPT_KEY` is our own AES-128-CBC+HMAC key protecting tokens
at rest; `worker/src/fernet.ts` is byte-compatible with Python's `cryptography.fernet`. Losing it =
unrecoverable ciphertext, which is **not** a Spotify failure. Rotating one never affects the other.

**§5 Biggest architectural simplification (noted, not proposed here).** A local-only design (the app
refreshes its own token on launch, no Worker / no D1 token store) would delete the Worker, D1 token
storage, `fernet.ts`, `seed_d1.py`, and the entire `invalid_grant` class — at the cost of no sync
while the app is closed (multi-day gaps lose plays, since Spotify returns only ~50/24h). A real
fork, worth a separate decision.
