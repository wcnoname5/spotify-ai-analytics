# Cloud Deployment (GitHub Actions + Cloudflare R2/Pages)

Runs the hourly Spotify sync in GitHub Actions and publishes a private static
dashboard on Cloudflare Pages. Your PC never needs to be on.
Everything fits in the free tiers (public-repo Actions minutes are free and unlimited).

```
GitHub Actions (hourly cron)
  ├─ download history.db + tokens.db from R2
  ├─ scripts/sync.py          → fetch recent plays from the Spotify API
  ├─ scripts/build_dashboard.py → site/*.html (static Plotly)
  ├─ upload both DBs back to R2 (tokens.db too — refresh tokens can rotate)
  └─ wrangler pages deploy site/
Cloudflare R2      = private storage for the two SQLite files
Cloudflare Pages   = hosts the dashboard
Cloudflare Access  = restricts the dashboard to your email
```

The local flow (wizard, MCP server, Streamlit dashboard) is untouched and
independent; the cloud copy of the DB lives its own life after the initial upload.

## One-time setup

Steps 0–2 are preparation, step 3 is one script that does everything else, steps 4–5 are verification.

### 0. Prerequisites (once per machine)

- Node.js ≥ 18 — the setup script drives Cloudflare via `npx wrangler`
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`) — the
  script uses it to write the repo secrets for you
- a Cloudflare account (free tier) and this repo pushed to your GitHub

### 1. Local data: run the wizard

```bash
uv run spotify-mcp        # OAuth → tokens.db, history import → history.db
```

The repo `.env` and the DBs (and `.env`) are in the platformdirs dirs (`spotify-mcp` prints the location), pass it as the script's 3rd argument.

> Warning: if `DEV=true` is set in `.env` under this repo root, the config and DB will be under root instead of platformdirs dirs (run `spotify-mcp path` to double check current path)

### 2. Cloudflare API token (the only dashboard step)

https://dash.cloudflare.com/profile/api-tokens → **Create Token** →
**Custom token**, with these three permissions:

| Permission | Used for |
|---|---|
| Account / **Workers R2 Storage** / Edit | CI downloads/uploads the DBs |
| Account / **Cloudflare Pages** / Edit | CI deploys the dashboard |
| Account / **Access: Apps and Policies** / Edit | step 3's login wall (script-only; unused but harmless in CI) |

Copy the token — it is shown only once.

### 3. Run the setup script

```bash
export CLOUDFLARE_API_TOKEN=<token from step 2>
bash scripts/setup_cloud.sh spotify-test spotify-dashboard ./data you@example.com
#                           ^bucket      ^pages-project    ^db dir ^your email
```

The first run opens a browser once for `wrangler login`. The script then does
**everything else**:

1. creates the private R2 bucket
2. uploads `history.db` + `tokens.db` into it
3. creates the Pages project
4. sets up the Access login wall. 
5. writes **all 6 GitHub secrets** via `gh`: `R2_BUCKET`, `CF_PAGES_PROJECT`,
   `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, plus `SPOTIFY_CLIENT_ID`
   and `TOKEN_ENCRYPT_KEY` read from the wizard's `.env` (values are never
   printed)

Every step is idempotent — rerunning is always safe. The end of the run
prints exactly what (if anything) is still missing and the command to fix it.
Two possible fails:

- Access step fails mentioning organization/team → onboard Zero Trust once at
  https://one.dash.cloudflare.com (any team name, **Free** plan, $0), rerun.
- Custom `SPOTIFY_USER_ID` (default is `default`)? Add it as an `env` entry
  in both workflow files.

### 4. Dry-run with sync-test

```bash
gh workflow run sync-test && gh run watch
```

or GitHub → **Actions** → **sync-test** → **Run workflow**. Green = the whole pipeline works: R2 round-trip, Spotify token refresh, dashboard build, Pages deploy.

It publishes to the *preview* URL `https://test.<project>.pages.dev`. You can test it by open in an incognito window: you must hit the Access login first, then see the dashboard.

> If sync-test doesn't show up in the Actions tab: GitHub only lists workflows that exist on the default branch : merge the branch first.

### 5. Go live

1. Testing used the throwaway `spotify-test` bucket. For the real one, rerun
   step 3 with the production bucket name (e.g. `spotify-analytics`). Or keep `spotify-test` is also fine.
2. Merge to main. The hourly cron in `sync.yml` activates automatically —
   first run within the hour (at :23).
3. Check the first green run in the Actions tab, then open
   `https://<project>.pages.dev`: Access login → dashboard. Done.

## Ongoing

- The cron runs hourly; the dashboard footer shows the last update (UTC).
- Nothing to maintain locally — token refresh (including rotation) is
  handled by the workflow via `tokens.db` round-tripping through R2.
- GitHub disables scheduled workflows after **60 days without repo activity**; any push (or re-enabling in the Actions tab) revives it.
- If tokens ever become invalid (e.g. you revoke the app), redo step 1's
  OAuth, then rerun step 3 — it re-seeds both DBs.

## Forking this setup

Fork the repo, then do the One-time setup above with your own Spotify app,
Cloudflare account, and secrets — the setup script works unchanged. Enable
the workflow in the Actions tab (disabled by default on forks).
