# Cloud Deployment (GitHub Actions + Cloudflare D1)

Runs the hourly Spotify sync in GitHub Actions, writing straight into
Cloudflare D1 through the Worker. Your PC never needs to be on.
Everything fits in the free tiers (public-repo Actions minutes are free and
unlimited; D1/Workers free tier is generous for a single-user history table).

```
GitHub Actions (hourly cron)
  └─ scripts/sync.py -> Worker (Bearer token) -> D1 (spotify-analytics)
Cloudflare D1     = single source of truth for listening history + encrypted tokens
Cloudflare Worker = the only thing that talks to D1 (worker/)
```

The local flow (wizard, MCP server) pulls a read-only sync cache of D1 into
local SQLite; it never writes to D1 directly.

## One-time setup

### 0. Prerequisites (once per machine)

- Node.js >= 18: the setup script and Worker deploy use `npx wrangler`
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`): the
  script uses it to write the repo secrets for you

- Create a Cloudflare account (free tier) and this repo pushed/forked to your GitHub

- Run `uv run spotify-mcp setup` finishing local OAuth (prompts for your
  Spotify Client ID, generates the token-encryption key, runs the OAuth flow, and optionally imports a Spotify JSON history export)

### 1. Run the setup script

```bash
bash scripts/setup_cloud.sh
```

The first run opens a browser once for `wrangler login`. The script does **everything else**:

1. ensures `.env` has `SPOTIFY_CLIENT_ID` (prompt) and generated `TOKEN_ENCRYPT_KEY`.  Existing values are never overwritten.
2. creates the `spotify-analytics` (prod) and `spotify-analytics-test` D1
   databases, patches their real `database_id`s into `worker/wrangler.toml`
3. applies `worker/migrations/` and deploys the Worker to both environments
4. generates the two Worker Bearer tokens and sets them as both the
   Worker-side `AUTH_TOKEN` secrets and the GitHub Actions secrets
   (`WORKER_URL`, `WORKER_AUTH_TOKEN`, `WORKER_TEST_URL`,
   `WORKER_TEST_AUTH_TOKEN`, plus `SPOTIFY_CLIENT_ID`/`TOKEN_ENCRYPT_KEY`
   from `.env`)
5. seeds D1 from your local data: the encrypted OAuth token row *and* all
   local listening history (wizard OAuth + JSON import) — each part is
   skipped when D1 is already up to date

Every step is idempotent — rerunning is always safe, and a run without
arguments also rotates the Bearer tokens. The end of the run prints exactly
what (if anything) is still missing and the command to fix it.

From the seed onward the hourly cron keeps D1 current. To re-seed manually
(e.g. after another JSON import, or with a restored `history.db` placed at
the local data path): `uv run python scripts/seed_d1.py [--force]`.

### 2. Dry-run with sync-test

```bash
gh workflow run sync-test && gh run watch
```

or GitHub -> **Actions** -> **sync-test** -> **Run workflow**. (The test Worker was already deployed by the setup script). Green = a sync
writes rows into the throwaway `spotify-analytics-test` D1 database.

> If sync-test doesn't show up in the Actions tab: GitHub only lists workflows that exist on the default branch or add `--ref <my-branch>` to reference workflow at specified branch

### 3. Go live

Merge to main. The hourly cron in `sync.yml` activates automatically — first
run within the hour (at :23), writing into the production `spotify-analytics`
D1 database.

## Ongoing

- The cron runs hourly against production D1.
- Worker deploys are manual and local: after changing `worker/`, run
  `cd worker && npx wrangler deploy` (and `--env test`), or just rerun the
  setup script. The cron never deploys.
- Nothing to maintain locally — the local SQLite cache is a pull-only mirror
  of D1, refreshed on demand; it's never written to independently.
- GitHub disables scheduled workflows after **60 days without repo
  activity**; any push (or re-enabling in the Actions tab) revives it.
- No automated backup: if you want a manual snapshot, `cd worker &&
  npx wrangler d1 export spotify-analytics --remote --output backup.sql`.

## Forking this setup

Fork the repo, then do the One-time setup above with your own Spotify app
and Cloudflare account — the setup script works unchanged. Enable the
workflow in the Actions tab (disabled by default on forks).
