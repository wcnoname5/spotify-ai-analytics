#!/usr/bin/env bash
# One-time Cloudflare setup for the cloud deployment (docs/DEPLOY.md), done
# from the terminal instead of clicking through the dashboard. Creates the R2
# bucket, seeds it with your two DBs, creates the Pages project, and (if you
# pass an email + API token) locks the dashboard behind Cloudflare Access.
#
# Usage:
#   bash scripts/setup_cloud.sh <r2-bucket> <pages-project> [data-dir] [allowed-email]
#
# Examples:
#   bash scripts/setup_cloud.sh spotify-test spotify-dashboard                    # infra only
#   CLOUDFLARE_API_TOKEN=... \
#   bash scripts/setup_cloud.sh spotify-test spotify-dashboard ./data me@mail.com # + Access
#
# With CLOUDFLARE_API_TOKEN exported, gh logged in, and the email argument
# given, this script does EVERYTHING: Cloudflare infra, the Access login
# wall, and all 6 GitHub Actions secrets. Every step is idempotent —
# rerunning is always safe (e.g. to re-seed the DBs or switch buckets).
#
# The Access step (5) needs the token to include permission
# "Account / Access: Apps and Policies / Edit" (see docs/DEPLOY.md step 2).
# It is scripted via the API because the dashboard's "Enable access policy"
# button moved in the 2025/26 UI revamp (and may not appear at all before a
# project's first deployment).
#
# Requires: node/npx, curl. Recommended: gh (GitHub CLI), logged in.

set -euo pipefail

BUCKET="${1:?usage: setup_cloud.sh <r2-bucket> <pages-project> [data-dir] [allowed-email]}"
PROJECT="${2:?usage: setup_cloud.sh <r2-bucket> <pages-project> [data-dir] [allowed-email]}"
DATA_DIR="${3:-./data}"
ALLOW_EMAIL="${4:-}"

WRANGLER="npx --yes wrangler@4"

for f in history.db tokens.db; do
  if [[ ! -f "$DATA_DIR/$f" ]]; then
    echo "error: $DATA_DIR/$f not found." >&2
    echo "Run the wizard first (uv run spotify-mcp). With DEV=true in the repo" >&2
    echo ".env the DBs land in ./data; otherwise pass the platformdirs data dir" >&2
    echo "as the 3rd argument (spotify-mcp prints its location)." >&2
    exit 1
  fi
done

echo "==> [1/5] Cloudflare login (opens a browser the first time)"
$WRANGLER whoami || $WRANGLER login

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
if [[ -z "$ACCOUNT_ID" ]]; then
  ACCOUNT_ID="$($WRANGLER whoami 2>/dev/null | grep -oE '[0-9a-f]{32}' | head -1 || true)"
fi

echo "==> [2/5] R2 bucket: $BUCKET"
$WRANGLER r2 bucket create "$BUCKET" \
  || echo "    bucket exists already — fine, continuing"

echo "==> [3/5] Seeding DBs into R2 (a few MB each)"
$WRANGLER r2 object put "$BUCKET/history.db" --file "$DATA_DIR/history.db" --remote
$WRANGLER r2 object put "$BUCKET/tokens.db" --file "$DATA_DIR/tokens.db" --remote

echo "==> [4/5] Pages project: $PROJECT"
$WRANGLER pages project create "$PROJECT" --production-branch main \
  || echo "    project exists already — fine, continuing"

# ---------------------------------------------------------------------------
# Step 5: Cloudflare Access — one self-hosted app covering the production
# domain AND preview URLs, allowing only $ALLOW_EMAIL (one-time PIN login).
# ---------------------------------------------------------------------------
ACCESS_DONE=0
if [[ -z "$ALLOW_EMAIL" ]]; then
  echo "==> [5/5] Access policy: SKIPPED (no email argument given)"
elif [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "==> [5/5] Access policy: SKIPPED — export CLOUDFLARE_API_TOKEN first"
  echo "    (token needs 'Account / Access: Apps and Policies / Edit'; then rerun)"
elif [[ -z "$ACCOUNT_ID" ]]; then
  echo "==> [5/5] Access policy: SKIPPED — could not auto-detect the account ID;"
  echo "    export CLOUDFLARE_ACCOUNT_ID and rerun"
else
  API="https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps"
  AUTH=(-H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json")

  # Use the real host (Pages may suffix it, e.g. myproj-53x.pages.dev);
  # a guessed name that belongs to someone else fails with error 12130.
  PAGES_HOST="$(curl -sS "${AUTH[@]}" \
    "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/pages/projects/$PROJECT" \
    | grep -oE '"subdomain": *"[^"]+"' | head -1 | cut -d'"' -f4 || true)"
  PAGES_HOST="${PAGES_HOST:-$PROJECT.pages.dev}"

  echo "==> [5/5] Access policy: allow only $ALLOW_EMAIL on $PAGES_HOST"

  # Only add domains not already covered (e.g. by the button-made preview app).
  APPS_JSON="$(curl -sS "${AUTH[@]}" "$API" || true)"
  NEED_DOMAINS=()
  echo "$APPS_JSON" | grep -qF "\"$PAGES_HOST\"" || NEED_DOMAINS+=("$PAGES_HOST")
  echo "$APPS_JSON" | grep -qF "\"*.$PAGES_HOST\"" || NEED_DOMAINS+=("*.$PAGES_HOST")

  if [[ ${#NEED_DOMAINS[@]} -eq 0 ]]; then
    echo "    already protected (production + previews) — nothing to do"
    ACCESS_DONE=1
  else
    echo "    covering: ${NEED_DOMAINS[*]}"
    DOMS="$(printf '"%s",' "${NEED_DOMAINS[@]}")"; DOMS="[${DOMS%,}]"
    RESP="$(curl -sS -X POST "${AUTH[@]}" "$API" --data @- <<EOF || true
{
  "name": "$PROJECT dashboard (${NEED_DOMAINS[0]})",
  "type": "self_hosted",
  "domain": "${NEED_DOMAINS[0]}",
  "self_hosted_domains": $DOMS,
  "session_duration": "24h",
  "app_launcher_visible": false,
  "policies": [
    {
      "name": "allow $ALLOW_EMAIL",
      "decision": "allow",
      "include": [ { "email": { "email": "$ALLOW_EMAIL" } } ]
    }
  ]
}
EOF
)"
    if echo "$RESP" | grep -q '"success": *true'; then
      echo "    done — production + preview URLs now require login"
      echo "    (one-time PIN sent to $ALLOW_EMAIL; verify in an incognito window)"
      ACCESS_DONE=1
    elif echo "$RESP" | grep -q 'does not belong to zone'; then
      # Cloudflare's public API refuses Access apps on *.pages.dev (it's
      # Cloudflare's domain, not a zone in your account). Only the built-in
      # button inside the Pages project can create this app — and that button
      # is hidden while the project has zero deployments, so publish a
      # placeholder first if needed.
      echo "    *.pages.dev can't be protected via the public API — the built-in"
      echo "    Pages button is the only way. Preparing it for you:"
      DEPLOYS="$(curl -sS "${AUTH[@]}" \
        "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/pages/projects/$PROJECT/deployments" || true)"
      if ! echo "$DEPLOYS" | grep -q '"id"'; then
        echo "    no deployment yet — publishing a placeholder page (the button"
        echo "    does not appear on an empty project)"
        TMP="$(mktemp -d)"
        echo "<h1>placeholder - the real dashboard arrives with the first sync</h1>" > "$TMP/index.html"
        $WRANGLER pages deploy "$TMP" --project-name "$PROJECT" --branch main --commit-dirty=true
        rm -rf "$TMP"
      fi
      cat <<EOF
    Finish with 2 clicks (~1 min):
      1. https://dash.cloudflare.com -> Workers & Pages -> $PROJECT ->
         Settings -> "Enable access policy"   (this one covers preview URLs;
         if asked to onboard Zero Trust: any team name, Free plan, \$0)
      2. Click "Enable access policy" a SECOND time — that one covers the
         production domain $PAGES_HOST.
      3. Verify: https://one.dash.cloudflare.com -> Access -> Applications
         lists the app(s) with a policy allowing $ALLOW_EMAIL (login = one-
         time PIN). Then open https://$PAGES_HOST in an incognito
         window: you must see a login screen, not the page.
EOF
      ACCESS_DONE=2
    else
      echo "    error: Access API call failed —" >&2
      echo "$RESP" >&2
      echo >&2
      echo "    If the error mentions a missing organization/team: onboard Zero" >&2
      echo "    Trust once at https://one.dash.cloudflare.com (any team name," >&2
      echo "    Free plan — it costs \$0), then rerun this script." >&2
    fi
  fi
fi

# ---------------------------------------------------------------------------
# GitHub Actions secrets — all six, if gh is available. Values are passed via
# --body and never printed. The two Spotify ones come from the wizard's .env
# (repo ./.env in DEV mode, otherwise next to the DBs in the data dir).
# ---------------------------------------------------------------------------
MISSING_SECRETS=()
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "==> Setting GitHub Actions secrets via gh (values are never printed)"
  gh secret set R2_BUCKET --body "$BUCKET"
  gh secret set CF_PAGES_PROJECT --body "$PROJECT"
  if [[ -n "$ACCOUNT_ID" ]]; then
    gh secret set CLOUDFLARE_ACCOUNT_ID --body "$ACCOUNT_ID"
  else
    MISSING_SECRETS+=("CLOUDFLARE_ACCOUNT_ID")
  fi
  if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    gh secret set CLOUDFLARE_API_TOKEN --body "$CLOUDFLARE_API_TOKEN"
  else
    MISSING_SECRETS+=("CLOUDFLARE_API_TOKEN")
  fi

  ENV_FILE=""
  for cand in "./.env" "$DATA_DIR/.env"; do
    [[ -f "$cand" ]] && { ENV_FILE="$cand"; break; }
  done
  for name in SPOTIFY_CLIENT_ID TOKEN_ENCRYPT_KEY; do
    val=""
    if [[ -n "$ENV_FILE" ]]; then
      val="$(grep -E "^${name}=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r')"
      val="${val%\"}"; val="${val#\"}"
    fi
    if [[ -n "$val" ]]; then
      gh secret set "$name" --body "$val"
    else
      MISSING_SECRETS+=("$name")
    fi
  done

  # Optional: custom user id. The tokens.db/history.db rows are keyed by it,
  # so CI must use the same value (workflows fall back to "default").
  uid=""
  if [[ -n "$ENV_FILE" ]]; then
    uid="$(grep -E '^SPOTIFY_USER_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r')"
    uid="${uid%\"}"; uid="${uid#\"}"
  fi
  if [[ -n "$uid" ]]; then
    gh secret set SPOTIFY_USER_ID --body "$uid"
  fi
  GH_DONE=1
else
  GH_DONE=0
fi

echo
echo "============================================================"
echo "Setup done: bucket \"$BUCKET\", Pages project \"$PROJECT\"."

if [[ "$ACCESS_DONE" == "2" ]]; then
  cat <<EOF

! Access policy: finish the 2 dashboard clicks printed above — until then
  the dashboard is PUBLIC.
EOF
elif [[ "$ACCESS_DONE" != "1" ]]; then
  cat <<EOF

! Access policy NOT set — the dashboard is still public. Rerun with your
  email (CLOUDFLARE_API_TOKEN needs Access: Apps and Policies / Edit):
     export CLOUDFLARE_API_TOKEN=<token>
     bash scripts/setup_cloud.sh $BUCKET $PROJECT $DATA_DIR <your-email>
EOF
fi

if [[ "$GH_DONE" != "1" ]]; then
  cat <<EOF

! GitHub secrets NOT set — gh is missing or not logged in. Run 'gh auth login'
  and rerun this script, or add these 6 by hand in GitHub -> repo Settings ->
  Secrets and variables -> Actions:
     R2_BUCKET=$BUCKET   CF_PAGES_PROJECT=$PROJECT   CLOUDFLARE_ACCOUNT_ID
     CLOUDFLARE_API_TOKEN   SPOTIFY_CLIENT_ID   TOKEN_ENCRYPT_KEY
EOF
elif [[ ${#MISSING_SECRETS[@]} -gt 0 ]]; then
  cat <<EOF

! Could not auto-fill these secrets — set them yourself (gh prompts for the
  value, nothing is echoed):
EOF
  for name in "${MISSING_SECRETS[@]}"; do
    echo "     gh secret set $name"
  done
  echo "   (SPOTIFY_CLIENT_ID / TOKEN_ENCRYPT_KEY live in the wizard's .env)"
else
  echo "All 6 GitHub Actions secrets are set."
fi

cat <<'EOF'

Next:
  - Dry-run the pipeline:  gh workflow run sync-test && gh run watch
    (or GitHub -> Actions -> sync-test -> Run workflow; deploys a Pages
     *preview* from the test bucket — production is never touched)
  - Go live: merge to main. The hourly cron in sync.yml only fires from the
    default branch; first run within the hour, then open
    https://<project>.pages.dev (Access login -> dashboard).
============================================================
EOF
