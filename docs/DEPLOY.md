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

## How the pieces fit (read once)

- **Workflows** (`.github/workflows/`):
  - `sync.yml`: production cron shedule run sync hourly,  only fire on **default branch (main)**. activate when you merge to `main`.
  - `sync-test.yml` — same steps, manual-only (`workflow_dispatch`). It defaults to a throwaway `spotify-test` bucket and deploys a Pages
    *preview*, so it can never touch production. Use it to prove the pipeline before merging.
- **Secrets**: repo secrets (GitHub → repo → Settings → Secrets and variables → Actions) are the only inputs a workflow can't read from the repo itself.
  `gh secret set NAME` writes to that exact same store from the terminal.  Workflows read them as `${{ secrets.NAME }}`; values are write-only (nobody can read them back, only overwrite) an auto-masked in logs.
- **Cloudflare pieces**: one R2 bucket (the two SQLite files), one Pages
  project (the static dashboard), one Access application (the login wall), and one API token that both CI and the setup script use for all of it.

## Privacy on a public repo

- Actions **logs are public**: `scripts/sync.py` prints row counts only, and
  GitHub masks all secret values in logs. Keep it that way — DO NOT add steps
  that print track names or dump the DB.
- The DBs live only in the private R2 bucket, never in the repo or artifacts.
- The dashboard URL is public but Cloudflare Access blocks everyone except
  the emails you allow.
- Forks do not inherit your secrets, and scheduled workflows are disabled on
  forks until the owner enables them.

## One-time setup

Steps 0–2 are prep, step 3 is one script that does everything else,
steps 4–5 are verification. Total: ~15 minutes.

### 0. Prerequisites (once per machine)

- Node.js ≥ 18 — the setup script drives Cloudflare via `npx wrangler`
- [GitHub CLI](https://cli.github.com/), logged in (`gh auth login`) — the
  script uses it to write the repo secrets for you
- a Cloudflare account (free tier) and this repo pushed to your GitHub

### 1. Local data: run the wizard

```bash
uv run spotify-mcp        # OAuth → tokens.db, history import → history.db
```

With `DEV=true` in the repo `.env` the DBs (and `.env`) live in the repo
checkout (`./data/`, `./.env`); otherwise in the platformdirs dirs —
`spotify-mcp` prints the location, pass it as the script's 3rd argument.

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
4. sets up the Access login wall. Note: Cloudflare's public API refuses
   Access apps on `*.pages.dev` ("domain does not belong to zone" — it's
   Cloudflare's domain, not yours), so the script publishes a placeholder
   deployment (the built-in button is hidden on empty projects) and prints
   the exact **2 dashboard clicks** that finish it: Pages project →
   Settings → "Enable access policy", clicked **twice** (first covers
   preview URLs, second covers production). Login = one-time PIN to your
   email.
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

or GitHub → **Actions** → **sync-test** → **Run workflow** (keep the default
`spotify-test` bucket). Green = the whole pipeline works: R2 round-trip, Spotify token refresh, dashboard build, Pages deploy.
It publishes to the *preview* URL `https://test.<project>.pages.dev`. You can test it by open in an incognito window: you must hit the Access login first, then see the dashboard.

(If sync-test doesn't show up in the Actions tab: GitHub only lists workflows
that exist on the default branch : merge the branch first; sync-test is
manual-only, so being on main never makes it run by itself.)

### 5. Go live

1. Testing used the throwaway `spotify-test` bucket. For the real one, rerun
   step 3 with the production bucket name (e.g. `spotify-analytics`) — it
   re-seeds the DBs there and updates the `R2_BUCKET` secret. (Keeping
   `spotify-test` as the production bucket also works; it's just a name.)
2. Merge to main. The hourly cron in `sync.yml` activates automatically —
   first run within the hour (at :23).
3. Check the first green run in the Actions tab, then open
   `https://<project>.pages.dev`: Access login → dashboard. Done.

<details><summary>Dashboard-click alternative (no CLI at all)</summary>

Everything the script does can be clicked in https://dash.cloudflare.com:

1. **R2 bucket**: R2 → Create bucket (keep it private, the default). Open the
   bucket and drag & drop `history.db` and `tokens.db` (keep exactly these
   names, at the bucket root).
2. **Pages project**: Workers & Pages → Create → Pages → "Upload assets" →
   pick a project name (any placeholder file works; the workflow overwrites
   it on every run).
3. **Access**: Zero Trust dashboard (https://one.dash.cloudflare.com) →
   Access → Applications → Add an application → **Self-hosted** → hostnames
   `<project>.pages.dev` **and** `*.<project>.pages.dev` → policy: Allow,
   Include → Emails → your email. (The old Pages "Enable access policy"
   shortcut button moved/disappeared in the 2025/26 dashboard revamp — go
   through Zero Trust directly.)
4. **Secrets**: repo → Settings → Secrets and variables → Actions → New
   repository secret, 6 of them: `R2_BUCKET`, `CF_PAGES_PROJECT`,
   `CLOUDFLARE_ACCOUNT_ID` (dashboard home, right sidebar),
   `CLOUDFLARE_API_TOKEN` (step 2), `SPOTIFY_CLIENT_ID` and
   `TOKEN_ENCRYPT_KEY` (from the wizard's `.env`).

</details>

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
