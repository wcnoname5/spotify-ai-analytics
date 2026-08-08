# Architecture

## Why it looks like this

Two decisions explain everything else. Both are forced by constraints outside the
code, not by preference.

**1. Spotify only ever returns your last ~50 plays.** So something has to collect them
on a schedule and keep running even when your app isn't up. That something is a
**Cloudflare Worker** (runs the hourly cron) writing to **D1** (stores the result).
It only collects and stores data.

**2. Spotify's commercial approval is impractical for a hobby app**, so this can't be
a service with accounts — every user runs their own copy against their own Cloudflare
account. That copy is a download-and-run `.exe` with no runtime dependencies, which is
why the app is **Tauri** and why nothing in the shipped path may assume `uv`, Python or
Node exists.

Much of the below is how those two decisions got implemented.

---

# Part A — mechanism

Facts rot: **if this half and the code disagree, one of them needs revising** — and it's usually this one.
Every claim is checkable, see [Verifying](#verifying-this-document). No file inventories or route tables; those
live in the code.

## The shape

```
                Spotify Web API
                   │        ▲
      hourly cron  │        │ OAuth (PKCE)
      (:07)        ▼        │
            ┌──────────────────────┐
            │  Cloudflare Worker   │  collect + store only
            └──────────┬───────────┘  one bearer token = tenancy
                 ┌─────▼─────┐
                 │    D1     │  source of truth
                 └─────┬─────┘
                       │  pull only, never pushed back
                 ┌─────▼──────────────┐
                 │  history.db        │  cache, disposable*
                 └─────┬──────────────┘
                       ▼
                  dashboard (Vue + Plotly)
```

\* except unsynced report rows — see [Part B](#rules).

- **D1 is the source of truth.** The app keeps a **pull-only** local SQLite mirror and
  reads *that* for every chart.
- **The Worker is D1's only door**, and not by choice: D1 has no public protocol you
  can connect to. Access is only through a binding Cloudflare injects into a Worker,
  so `env.DB` in there is the only handle to the database that exists.
- **Python ships with nothing.** Report generation runs from a checkout only.

## Who owns what

**Rust shell** (`src-tauri/`) does what a webview cannot: sole writer of
`config.json`, binds the OAuth loopback port, runs the Cloudflare deploy over REST,
manages the two windows. It runs no queries.

`build.rs` runs esbuild on the Worker at *your* compile time and `cloudflare.rs`
`include_str!`s the result, so the Worker's JavaScript is a string baked inside the
`.exe`.
Two consequences: 
 - a broken Worker is a **Rust compile error** rather than a failed Deploy on someone's machine
 - the Worker's code is versioned with the app: the user must re-deploy the Worker when a new app version changes the Worker's code.

**Frontend TS** (`apps/tauri/src/`) owns everything else: analytics SQL, all Worker
calls, PKCE, Fernet, export parsing. It reads SQLite via `tauri-plugin-sql` and
reaches the Worker via `@tauri-apps/plugin-http` — never the webview `fetch`, since
the Worker sends no CORS headers.
 Two windows come from one bundle, switched on
`location.hash`: `main` starts hidden and is revealed once config exists, `setup` is
created on demand.

**Worker & D1** (`worker/`) has exactly two entry points:

- `fetch()` — a flat exact-match router with auth *before* routing, so even a 404
  needs the token. Routes live in `worker/src/index.ts`.
- `scheduled()` — the hourly cron: decrypt the token row, refresh if expired
  (**writing the rotated refresh token back to D1 first** — Spotify rotates them, and
  losing one mid-flight locks the account out until you re-authorize), fetch recent
  plays, insert, advance the cursor.

One Worker only ever serves one person, so we keep one static bearer token instead of accounts.
- D1 holds four tables: `listening_history`, `spotify_tokens`, `sync_state`, `reports`.

**Shared code** — the answer to this repo's most persistent bug, the same rule
implemented twice and drifting:

| Where | Alias | Covers | Shared by |
|---|---|---|---|
| `packages/shared-ts/` | `@shared` | Fernet, PKCE, `listening_history.id`, export parsing | Worker + frontend |
| `packages/core/spotify_core/db/sql/` | `@sql` | migrations, analytics SQL | frontend + Python |

`shared-ts` is web-standard APIs only — the same code runs in a Worker isolate and a
WebView. Config is the third such rule, split by direction: `config.rs` writes,
`config_file.py` reads.

**Python** is not in the installer. The report graph is a one-shot subprocess whose
repo root resolves at *compile* time, so it only runs on the machine that built the
binary — it is the only surviving Python. The old MCP server (and the Python Spotify
client behind it) was removed on the `migrate-TS` branch; it is recoverable from the
`mcp-python-archive` git tag, and any future version will likely be TypeScript.

## Data flow: one play to a chart

1. You play a track.
2. At `:07` the cron fetches recent plays, computes
   `id = sha1("<track_uri>:<second-precision UTC ISO>")`, `INSERT OR IGNORE` into D1.
3. You open the app; it pulls everything past its local cursor into `history.db`.
4. The dashboard runs shared `.sql` against `history.db`.

A Spotify **data export** enters by a different door — parsed locally, POSTed to the
Worker — but computes **the same id**, so export and cron dedupe against each other
for free.

## Configuration

One flat JSON file, and **nothing reads the cwd**:

```
$SPOTIFY_CONFIG set  ->  that exact path        (data lands in ./data beside it)
otherwise            ->  platformdirs config dir / config.json
```

---

# Part B — rules

Why it is shaped this way and what must not be broken. Changes only when a decision
is deliberately reversed.

## Invariants

Each came from a real bug. Where a test enforces it, the test is the authority.

| Rule | Why | Test |
|---|---|---|
| One implementation of `listening_history.id` | Two meant the same play, via cron and via export, counted twice in every chart | ✅ `rowid.test.ts` |
| Every ingress is `INSERT OR IGNORE` on that hash | Makes re-import and re-sync consequence-free — why no "did I already import this?" state exists anywhere | ✅ `sync.test.ts` |
| Pull cursor is `(played_at, id)`, never `played_at` | Two plays in the same second across a page boundary were skipped **permanently** | ❌ Worker untested by choice |
| Startup compares row counts, not just the cursor | The cursor only moves forward, so rows *older* than local max never arrive — exactly what "fetch 50 now, import the export next week" produces | ✅ `sync.test.ts` |
| Report delete hits D1 **before** the local row | The report cursor is `MAX(generated_at)`; a local-only delete lowers it and the next startup pulls the row back | ✅ `sync.test.ts` |
| `ensure_fernet_key` never regenerates | Orphans every token encrypted with the old key | ✅ `config.rs` |
| A deploy reuses the recorded stack name | A different name does not error — it silently builds a *second* Worker and an empty D1 | ❌ |

**No Worker aggregation endpoints, ever.** The Worker collects and stores; analytics
stay local. So a new filter or date range is a pure SQL change that ships without a
deploy. Its only non-sync job is report CRUD.

**The cache is disposable, except** unsynced report rows, which exist nowhere else.
The `synced=0` rows *are* the outbox; there is no queue table.

**The encryption key crosses into the webview on purpose**, so one `fernet.ts` serves
both the encrypting app and the decrypting cron. It protects D1 in transit and at
rest — not local file access.

**Setup order is `client_id → worker → oauth → history`**, because D1 is the only
place a token may live, so there is nothing to authorize *into* until the Worker
exists. Settings apply on restart.

## Known workarounds (not invariants — fix properly if they bite)

- **No wrapping transaction in TS sync.** `sqlx` pooling routes `COMMIT` unreliably
  and the inserts are idempotent, so today it costs nothing. If you ever need real
  atomicity, fix it with a single pinned connection rather than routing around it.
- **D1 concurrency is safe by construction, not by locking**: single-writer SQLite,
  and the cron and report writes share no rows. True only while report writes stay one
  statement each. Fragile; revisit if either writer grows.

## Writing shared SQL

The `.sql` files run under two drivers, which constrains them:

- Indexed params `?1 … ?N`, never positional.
- Optional filters are baked-in null guards — `(?1 IS NULL OR played_at >= ?1)` —
  never assembled programmatically. Bind `NULL` to mean "no filter".
- Timezone is a bound parameter: `datetime(played_at, ?3)`.
- The `.sql` owns query logic (skip thresholds, week start, segments); row shaping
  stays in the calling language and stays thin.

`plays_by_hour.sql` is TS-only and `activity_pattern.sql` is Python-only — not
duplicates waiting to be merged.

The report subprocess contract is **markdown on stdout, diagnostics on stderr,
non-zero exit on failure**. Keeping it that narrow is what leaves both a PyInstaller
sidecar and a LangGraph.js rewrite open. **How reports ship is undecided.**

## Deliberate non-goals

| | |
|---|---|
| Keychain | `TOKEN_ENCRYPT_KEY` is plaintext in `config.json` |
| macOS | `rfd` needs the main thread there; `lib.rs` is marked |
| Shipping reports | v1 is dashboard-only |
| MCP | Removed on `migrate-TS` (see `mcp-python-archive` tag); may return later, likely in TS |
| Report tombstones | A second machine keeps a stale local row, but never pushes it back, so D1 stays correct |
| Export/API field merge | Both `INSERT OR IGNORE`, first writer wins. Affects `ms_played`/`platform`/`skipped` richness only, never a chart number |

---

## Verifying this document

```bash
git ls-files packages/shared-ts packages/core/spotify_core/db/sql   # the shared set
grep -n "pathname ===" worker/src/index.ts                          # the real routes
grep -n "crons" worker/wrangler.toml                                # the cron schedule
grep -rn "CREATE TABLE" packages/core/spotify_core/db/sql/migrations/
grep -n "generate_handler!" -A 20 apps/tauri/src-tauri/src/lib.rs   # Rust's surface
cd apps/tauri && npm test                                           # the invariants above
```

Conventions are in `CLAUDE.md`. Release and E2E procedures are in `shipping-v1.md`,
which is temporary.
