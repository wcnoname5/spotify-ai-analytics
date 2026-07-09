# Cloud Deployment (GitHub Actions + Cloudflare R2/Pages)

Runs the hourly Spotify sync in GitHub Actions and publishes a private static
dashboard on Cloudflare Pages — your PC never needs to be on. Everything fits
in the free tiers (public-repo Actions minutes are free and unlimited).

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
independent; the cloud copy of the DB lives its own life after the initial
upload.

## Privacy on a public repo

- Actions **logs are public**: `scripts/sync.py` prints row counts only, and
  GitHub masks all secret values in logs. Keep it that way — don't add steps
  that print track names or dump the DB.
- The DBs live only in the private R2 bucket, never in the repo or artifacts.
- The dashboard URL is public but Cloudflare Access blocks everyone except
  the emails you allow.
- Forks do not inherit your secrets, and scheduled workflows are disabled on
  forks until the owner enables them.

## One-time setup

### 1. Local: get tokens and history

Run the wizard as usual so you have a working local install:

```bash
uv run spotify-mcp        # OAuth → data/tokens.db, history import → data/history.db
```

(With `DEV=true` in the repo `.env` the files are in `./data/`; otherwise in
the platformdirs data dir — `spotify-mcp` prints the location.)

### 2. Cloudflare: R2 bucket + Pages + Access

Everything in this step happens in the Cloudflare dashboard
(https://dash.cloudflare.com — free account is enough). You will collect
**6 values** along the way; step 4 pastes them into GitHub. No CLI tools
needed on your machine.


1. **Account ID** → dashboard home, right-hand sidebar (or any domain
   overview page). Copy it. `(value 1)`
2. **R2 bucket** → R2 → Create bucket, e.g. `spotify-analytics`. Keep it
   private (the default — don't enable public access). Bucket name is
   `(value 2)`.
3. **R2 API token** R2 → Overview → API Tokens → Create Account API oken 
   permission **Object Read & Write**, scoped to your bucket. Cloudflare
   shows an **Access Key ID** `(value 3)` and **Secret Access Key**
   `(value 4)` once — copy both now.
4. **Pages project** → Workers & Pages → Create → Pages → "Upload assets" →
   pick a project name `(value 5)` — you can create it with any placeholder
   file; the workflow overwrites it on every run.
5. **Access (make the page private)** — no manual Zero Trust configuration
   needed; Pages has a built-in shortcut:
   1. In your Pages project → **Settings → General → Enable access policy**.
      (If Cloudflare asks you to onboard Zero Trust first: pick any team
      name and the **Free** plan — it costs $0 but may ask for a payment
      method.)
   2. That first click only protects *preview* URLs. **Select "Enable
      access policy" again** — this second click adds a policy covering the
      production `<project>.pages.dev` domain too. You should end up with
      two Access applications (one for `*.<project>.pages.dev` previews,
      one for `<project>.pages.dev`).
   3. Check who's allowed in: Zero Trust dashboard
      (https://one.dash.cloudflare.com) → **Access → Applications** → open
      each auto-created app → Policies. It should allow only your email;
      login works via a one-time PIN sent to that email.
   4. Verify with a private/incognito window: opening the page must show a
      Cloudflare login screen, not the dashboard.

   Do this **before** the first real deploy so the dashboard is never
   publicly reachable.
6. **Cloudflare API token** (this is different from the R2 token in 3) →
   My Profile → API Tokens → Create Token → Custom token → permission
   **Account / Cloudflare Pages / Edit**. Copy it. `(value 6)`

### 3. Upload the DBs to R2 (initial seed)

In the R2 bucket page, just **drag & drop** `history.db` and `tokens.db`
(browser uploads work up to 300 MB — the DBs are a few MB). Where the files
are on your machine:

- If you ran the wizard normally: the `spotify-mcp` data dir —
  Windows `%LOCALAPPDATA%\spotify-mcp\spotify-mcp\`,
  macOS `~/Library/Application Support/spotify-mcp/`,
  Linux `~/.local/share/spotify-mcp/`.
- If you develop with `DEV=true`: `./data/` in the repo checkout.

Keep the object names exactly `history.db` and `tokens.db` (the workflow
looks them up by these names, at the bucket root).

<details><summary>CLI alternative (only if you already have aws cli)</summary>

```bash
export AWS_ACCESS_KEY_ID=<value ③>
export AWS_SECRET_ACCESS_KEY=<value ④>
aws s3 cp history.db s3://<bucket>/history.db --endpoint-url https://<account-id>.r2.cloudflarestorage.com
aws s3 cp tokens.db  s3://<bucket>/tokens.db  --endpoint-url https://<account-id>.r2.cloudflarestorage.com
```

The hourly workflow itself uses aws cli too, but it's preinstalled on GitHub's
runners — you never need it locally.
</details>

### 4. GitHub repo secrets

Secrets are per-repository encrypted variables that only Actions runs can
read. On your repo's GitHub page: **Settings → Secrets and variables → Actions → New repository secret**, then add these 8, one at a time
(Name must match exactly):

| Name | Where to get the value |
|---|---|
| `SPOTIFY_CLIENT_ID` | your local `.env`, written by the wizard (same folder as the DBs in step 3, e.g. `%LOCALAPPDATA%\spotify-mcp\spotify-mcp\.env`) |
| `TOKEN_ENCRYPT_KEY` | same `.env` file — must be the key that encrypted the tokens.db you uploaded |
| `CLOUDFLARE_ACCOUNT_ID` | step 2 value (1) |
| `R2_BUCKET` | step 2 value (2) (bucket name) |
| `R2_ACCESS_KEY_ID` | step 2 value (3) |
| `R2_SECRET_ACCESS_KEY` | step 2 value (4) |
| `CF_PAGES_PROJECT` | step 2 value (5) (Pages project name) |
| `CLOUDFLARE_API_TOKEN` | step 2 value (6) (the Pages:Edit token, **not** the R2 one) |

If your local setup used a custom `SPOTIFY_USER_ID` (default is `default`),
also add it as an `env` entry in `.github/workflows/sync.yml`.

### 5. First run

Actions → `sync` → **Run workflow**. When it's green, open
`https://<project>.pages.dev` — you should hit the Access login, then the
dashboard.

## Ongoing

- The cron runs hourly; the dashboard footer shows the last update (UTC).
- Nothing to maintain locally — token refresh (including rotation) is
  handled by the workflow via tokens.db round-tripping through R2.
- GitHub disables scheduled workflows after **60 days without repo
  activity**; any push (or re-enabling in the Actions tab) revives it.
- If tokens ever become invalid (e.g. you revoke the app), redo step 1's
  OAuth and step 3's tokens.db upload.

## Forking this setup

Fork the repo, then do the One-time setup above with your own Spotify app,
Cloudflare account, and secrets. Enable the workflow in the Actions tab
(disabled by default on forks).
