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

- Node.js >= 18 — the setup script and Worker deploy use `npx wrangler`
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`) — the
  script uses it to write the repo secrets for you
- a Cloudflare account (free tier) and this repo pushed to your GitHub
- a `.env` file at the repo root (or `data/.env`) with the four values the
  setup script forwards into GitHub Actions secrets:

  ```bash
  SPOTIFY_CLIENT_ID=      # Spotify app client ID (developer.spotify.com dashboard)
  TOKEN_ENCRYPT_KEY=      # Fernet key encrypting the tokens; the one your existing
                          # tokens were encrypted with, or for a fresh install:
                          # uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  CLOUDFLARE_ACCOUNT_ID=  # Cloudflare dashboard -> right sidebar of any zone/Workers page
  CLOUDFLARE_API_TOKEN=   # dash.cloudflare.com/profile/api-tokens -> Create Token,
                          # needs Workers Scripts:Edit + D1:Edit permissions
  ```

  Missing values aren't fatal — the script ends by printing exactly which
  secrets you still need to `gh secret set` by hand. The two Worker Bearer
  tokens (`WORKER_AUTH_TOKEN`/`WORKER_TEST_AUTH_TOKEN`) do NOT go in `.env` —
  you pass them on the command line in step 1, and `WORKER_URL`/
  `WORKER_TEST_URL` are auto-captured from the deploy output.

### 1. Run the setup script

```bash
bash scripts/setup_cloud.sh <worker-auth-token> <worker-test-auth-token>
#                           ^Bearer token for sync.yml ^for sync-test.yml
```

Generate the tokens yourself, e.g. `openssl rand -hex 32`. The first run
opens a browser once for `wrangler login`. The script then does
**everything else**:

1. creates the `spotify-analytics` (prod) and `spotify-analytics-test` D1
   databases, and patches their real `database_id`s into `worker/wrangler.toml`
2. applies `worker/migrations/` and deploys the Worker to both environments
3. sets the Worker-side `AUTH_TOKEN` secret (via `wrangler secret put`) for
   both the prod and `--env test` Worker, from the tokens passed on the
   command line — without this step every Worker request 401s
4. writes the GitHub secrets via `gh`: `WORKER_URL`, `WORKER_AUTH_TOKEN`,
   `WORKER_TEST_URL`, `WORKER_TEST_AUTH_TOKEN`, plus
   `SPOTIFY_CLIENT_ID`/`TOKEN_ENCRYPT_KEY`/`CLOUDFLARE_ACCOUNT_ID`/
   `CLOUDFLARE_API_TOKEN` read from the `.env` of step 0

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
D1 database.

## Ongoing

- The cron runs hourly against production D1.
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
