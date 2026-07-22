# Cloud Deployment (Cloudflare Worker + D1)

The hourly Spotify sync runs inside the Cloudflare Worker itself (a
`scheduled()` cron handler) writing straight into D1. Your PC never needs to
be on. Everything fits in the Workers/D1 free tier for a single-user history
table.

```
Cloudflare Worker (worker/)
  ├─ cron scheduled() hourly at :07 -> Spotify API -> D1  (primary, worker/src/sync.ts)
  └─ HTTP API (Bearer token)        -> D1                 (used by local scripts)
Cloudflare D1 (spotify-analytics) = single source of truth: listening history + encrypted tokens
```

The local flow (wizard, MCP server) pulls a read-only sync cache of D1 into
local SQLite; it never writes to D1 directly.

## One-time setup

### 0. Prerequisites (once per machine)

- Node.js >= 18: the Worker deploy uses `npx wrangler`
- A Cloudflare account (free tier)
- Run `uv run spotify-mcp setup` finishing local OAuth (prompts for your
  Spotify Client ID, generates the token-encryption key, runs the OAuth flow,
  and optionally imports a Spotify JSON history export)

### 1. Deploy

In the desktop app this is the **Deploy to Cloudflare** button on the Setup
page's Cloud card. The equivalent from a terminal:

```bash
uv run spotify-mcp cloud deploy [--name spotify-analytics] [--api-token <token>]
```

`--api-token` (create one at dash.cloudflare.com → API Tokens, Permissions: enable `[Account] [D1] [Edit]` and `[Account] [Workers Scripts] [Edit]`) skips `wrangler login`; without it wrangler opens a
browser on the first run, which is why the GUI always passes one. The command
does everything else:

1. creates the D1 database and resolves its `database_id` into a throwaway
   wrangler config — the repo's `worker/wrangler.toml` is never written, so a
   `--name` test deploy cannot redirect a later production one
2. applies `worker/migrations/` and deploys the Worker — **this activates the
   hourly cron** (`7 * * * *`)
3. sets the Worker secrets: the Bearer `AUTH_TOKEN`, plus `SPOTIFY_CLIENT_ID` /
   `TOKEN_ENCRYPT_KEY` for the cron
4. writes `WORKER_URL` / `WORKER_AUTH_TOKEN` back to the resolved `.env`
5. seeds D1 from your local data — the encrypted OAuth token row *and* all
   local listening history (wizard OAuth + JSON import). Each part is skipped
   when D1 is already up to date

`SPOTIFY_CLIENT_ID` and `TOKEN_ENCRYPT_KEY` must already exist (the setup wizard
creates both); this command never prompts, so it can run as a spawned child.

Every step is idempotent — rerunning is safe and **keeps** the existing Bearer
token. Pass `--rotate` to mint a new one, which invalidates every other machine
pointing at this Worker. Cloudflare secrets are write-only, so the copy in your
`.env` is the only one that exists: back that file up.

From the seed onward the Worker cron keeps D1 up to current. To re-seed manually
(e.g. after another JSON import, or with a restored `history.db` placed at the
local data path): `uv run spotify-mcp cloud seed [--force]`.

### 2. (Optional) Dry-run the cron without waiting for :07

`wrangler dev` does **not** see the deployed Worker secrets, so first create a
gitignored `worker/.dev.vars` with the cron's two secrets from `.env`:

```bash
grep -E "^(SPOTIFY_CLIENT_ID|TOKEN_ENCRYPT_KEY)=" .env > worker/.dev.vars
cd worker && npx wrangler dev --remote --test-scheduled
curl "http://127.0.0.1:8787/__scheduled?cron=7+*+*+*+*"
```

This runs the real `scheduled()` handler against production D1 — which is the
safe target: a token refresh writes back to the same row the live cron reads.
Avoid running it within a few minutes of xx:07 so the two never race on
Spotify's refresh-token rotation.

## Ongoing

- The Worker cron runs hourly at :07 against production D1. Health check:
  Cloudflare dashboard -> the Worker -> **Cron Events** / **Workers Logs**.
- Worker deploys are manual and local: after changing `worker/`, run
  `cd worker && npx wrangler deploy`, or just rerun the setup script.
  Deploying is also how the cron schedule/code updates.
- Nothing to maintain locally — the local SQLite cache is a pull-only mirror
  of D1, refreshed on demand; it's never written to independently.
- No automated backup: if you want a manual snapshot, `cd worker &&
  npx wrangler d1 export spotify-analytics --remote --output backup.sql`.

## Forking this setup

Fork the repo, then do the One-time setup above with your own Spotify app and
Cloudflare account — the setup script works unchanged, and the cron is live as
soon as the Worker deploys.
