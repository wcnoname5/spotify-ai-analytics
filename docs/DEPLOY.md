# Cloud Deployment (GitHub Actions + Cloudflare D1)

Runs the hourly Spotify sync in GitHub Actions, writing straight into
Cloudflare D1 through the Worker. Your PC never needs to be on.
Everything fits in the free tiers (public-repo Actions minutes are free and
unlimited; D1/Workers free tier is generous for a single-user history table).

```
GitHub Actions (hourly cron)
  └─ scripts/sync.py -> Worker (Bearer token) -> D1 (spotify-analytics)
       └─ backup step: wrangler d1 export --remote -> R2 (backup.sql)
Cloudflare D1     = single source of truth for listening history + encrypted tokens
Cloudflare Worker = the only thing that talks to D1 (worker/)
Cloudflare R2     = backup copy only (never read back automatically)
```

The local flow (wizard, MCP server) pulls a read-only sync cache of D1 into
local SQLite; it never writes to D1 directly.

## One-time setup

### 0. Prerequisites (once per machine)

- Node.js >= 18 — the setup script and Worker deploy use `npx wrangler`
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`) — the
  script uses it to write the repo secrets for you
- a Cloudflare account (free tier) and this repo pushed to your GitHub

### 1. Run the setup script

```bash
bash scripts/setup_cloud.sh <worker-auth-token> <worker-test-auth-token> [r2-backup-bucket]
#                           ^Bearer token for sync.yml ^for sync-test.yml  ^defaults to spotify-analytics-backup
```

Generate the tokens yourself, e.g. `openssl rand -hex 32`. The first run
opens a browser once for `wrangler login`. The script then does
**everything else**:

1. creates the `spotify-analytics` (prod) and `spotify-analytics-test` D1
   databases, and patches their real `database_id`s into `worker/wrangler.toml`
2. creates the R2 backup bucket
3. applies `worker/migrations/` and deploys the Worker to both environments
4. sets the Worker-side `AUTH_TOKEN` secret (via `wrangler secret put`) for
   both the prod and `--env test` Worker, from the tokens passed on the
   command line — without this step every Worker request 401s
5. writes the GitHub secrets via `gh`: `WORKER_URL`, `WORKER_AUTH_TOKEN`,
   `WORKER_TEST_URL`, `WORKER_TEST_AUTH_TOKEN`, `R2_BACKUP_BUCKET`, plus
   `SPOTIFY_CLIENT_ID`/`TOKEN_ENCRYPT_KEY`/`CLOUDFLARE_ACCOUNT_ID`/
   `CLOUDFLARE_API_TOKEN` read from a local `.env` if present

Every step is idempotent — rerunning is always safe (e.g. after rotating a
token or redeploying the Worker). The end of the run prints exactly what (if
anything) is still missing and the command to fix it.

### 2. One-time historical backfill (existing users only)

If you're migrating from the old R2-hosted SQLite setup, run
`scripts/migrate_r2_to_d1.py` once to backfill existing history/tokens into
D1. Fresh installs can skip this — `sync.py` populates D1 from scratch.

### 3. Dry-run with sync-test

```bash
gh workflow run sync-test && gh run watch
```

or GitHub -> **Actions** -> **sync-test** -> **Run workflow**. Green = the
Worker deploys, migrations apply, and a sync writes rows into the throwaway
`spotify-analytics-test` D1 database.

> If sync-test doesn't show up in the Actions tab: GitHub only lists
> workflows that exist on the default branch — merge the branch first.

### 4. Go live

Merge to main. The hourly cron in `sync.yml` activates automatically — first
run within the hour (at :23), writing into the production `spotify-analytics`
D1 database and depositing a `backup.sql` dump in R2 afterward.

## Ongoing

- The cron runs hourly against production D1.
- Nothing to maintain locally — the local SQLite cache is a pull-only mirror
  of D1, refreshed on demand; it's never written to independently.
- GitHub disables scheduled workflows after **60 days without repo
  activity**; any push (or re-enabling in the Actions tab) revives it.
- The R2 `backup.sql` dump is a safety net only — nothing reads it back
  automatically. Restore manually via `wrangler d1 execute` if D1 is ever
  lost.

## Forking this setup

Fork the repo, then do the One-time setup above with your own Spotify app
and Cloudflare account — the setup script works unchanged. Enable the
workflow in the Actions tab (disabled by default on forks).
