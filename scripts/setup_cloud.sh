#!/usr/bin/env bash
# One-time Cloudflare setup for the D1-backed deployment (docs/DEPLOY.md).
# Creates the prod D1 database, applies the Worker's migrations, deploys the
# Worker (whose hourly cron starts syncing immediately), sets the Worker
# secrets, and seeds D1.
#
# Usage:
#   bash scripts/setup_cloud.sh [worker-auth-token]
#
# Requires: node/npx (wrangler).

set -euo pipefail

# Windows ships a "python3"/"python" shim (App Execution Alias) that prints an
# install nag and exits nonzero when no real interpreter is installed, instead
# of failing command -v. Actually invoke each candidate to find a working one.
resolve_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'pass' >/dev/null 2>&1; then
      echo "$c"; return
    fi
  done
  echo "uv run python"
}
PYTHON="$(resolve_python)"

gen_hex() { openssl rand -hex 32 2>/dev/null || $PYTHON -c 'import secrets; print(secrets.token_hex(32))'; }
WORKER_AUTH_TOKEN="${1:-$(gen_hex)}"

PROD_DB="spotify-analytics"
WRANGLER="npx --yes wrangler@4"
WORKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../worker" && pwd)"

# ---------------------------------------------------------------------------
# [0/4] .env: ensure SPOTIFY_CLIENT_ID (prompt) and TOKEN_ENCRYPT_KEY (generate).
# Existing values are never overwritten
# ---------------------------------------------------------------------------
ENV_FILE=""
for cand in "./.env" "./data/.env"; do
  [[ -f "$cand" ]] && { ENV_FILE="$cand"; break; }
done
[[ -z "$ENV_FILE" ]] && { ENV_FILE="./.env"; touch "$ENV_FILE"; }

env_get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//'; }
env_set() { # upsert KEY=value in $ENV_FILE (overwrites an existing line)
  if grep -qE "^$1=" "$ENV_FILE"; then
    sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

echo "==> [0/4] Checking $ENV_FILE"
if [[ -z "$(env_get SPOTIFY_CLIENT_ID)" ]]; then
  read -r -p "    Paste your Spotify Client ID (developer.spotify.com dashboard): " CLIENT_ID
  [[ -z "$CLIENT_ID" ]] && { echo "    Client ID is required."; exit 1; }
  printf 'SPOTIFY_CLIENT_ID=%s\n' "$CLIENT_ID" >> "$ENV_FILE"
fi
if [[ -z "$(env_get TOKEN_ENCRYPT_KEY)" ]]; then
  NEW_KEY="$($PYTHON -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null \
    || uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  printf 'TOKEN_ENCRYPT_KEY=%s\n' "$NEW_KEY" >> "$ENV_FILE"
  echo "    Generated a new TOKEN_ENCRYPT_KEY in $ENV_FILE — do NOT lose this file;"
  echo "    losing the key makes stored tokens unrecoverable."
fi

echo "==> [1/4] Cloudflare login (opens a browser the first time)"
(cd "$WORKER_DIR" && $WRANGLER whoami) || (cd "$WORKER_DIR" && $WRANGLER login)

echo "==> [2/4] D1 database: $PROD_DB"
(cd "$WORKER_DIR" && $WRANGLER d1 create "$PROD_DB") \
  || echo "    $PROD_DB exists already — fine, continuing"

echo "==> [2b/4] Patching worker/wrangler.toml with the real database_id"
[[ -f "$WORKER_DIR/wrangler.toml" ]] || cp "$WORKER_DIR/wrangler.toml.example" "$WORKER_DIR/wrangler.toml"
D1_LIST_JSON="$(cd "$WORKER_DIR" && $WRANGLER d1 list --json)"
$PYTHON - "$WORKER_DIR/wrangler.toml" "$PROD_DB" <<PYEOF
import json, re, sys
toml_path, prod_name = sys.argv[1:3]
databases = json.loads('''$D1_LIST_JSON''')
by_name = {d["name"]: d["uuid"] for d in databases}
prod_id = by_name[prod_name]

text = open(toml_path, encoding="utf-8").read()

def patch(text, db_name, db_id):
    pattern = re.compile(
        r'(database_name = "%s"\n(?:[^\n]*\n)*?database_id = )"[^"]*"' % re.escape(db_name)
    )
    new_text, count = pattern.subn(lambda m: m.group(1) + '"%s"' % db_id, text, count=1)
    if count != 1:
        raise SystemExit(f"could not find database_id line for {db_name} in {toml_path}")
    return new_text

text = patch(text, prod_name, prod_id)
open(toml_path, "w", encoding="utf-8").write(text)
print(f"    {prod_name} -> {prod_id}")
PYEOF

echo "==> [3/4] Apply migrations + deploy the Worker (the hourly cron goes live here)"
(cd "$WORKER_DIR" && $WRANGLER d1 migrations apply "$PROD_DB" --remote)
DEPLOY_OUT="$(cd "$WORKER_DIR" && $WRANGLER deploy)"
echo "$DEPLOY_OUT"
WORKER_URL="$(echo "$DEPLOY_OUT" | grep -oE 'https://[^ ]+\.workers\.dev' | head -1 || true)"

if [[ -z "$WORKER_URL" ]]; then
  echo "    warning: could not parse the Worker URL from the deploy output —"
  echo "    set WORKER_URL manually in $ENV_FILE."
fi

echo "==> [3b/4] Worker secrets (never printed): AUTH_TOKEN + the cron's Spotify credentials"
printf '%s' "$WORKER_AUTH_TOKEN" | (cd "$WORKER_DIR" && $WRANGLER secret put AUTH_TOKEN)
# Without these two the deployed cron fails every hour (SPOTIFY_USER_ID is
# optional — the Worker defaults it to "default").
printf '%s' "$(env_get SPOTIFY_CLIENT_ID)" | (cd "$WORKER_DIR" && $WRANGLER secret put SPOTIFY_CLIENT_ID)
printf '%s' "$(env_get TOKEN_ENCRYPT_KEY)" | (cd "$WORKER_DIR" && $WRANGLER secret put TOKEN_ENCRYPT_KEY)

# Write WORKER_* to .env, OVERWRITING stale values: each run without args
# rotates the Bearer token on the Worker, so a leftover old value in .env
# would 401 every local script.
[[ -n "$WORKER_URL" ]] && env_set WORKER_URL "$WORKER_URL"
env_set WORKER_AUTH_TOKEN "$WORKER_AUTH_TOKEN"

echo "==> [4/4] Seeding D1 (tokens + history) — skips whatever D1 already has"
sleep 5
# A freshly-set `wrangler secret put` can take a few seconds to propagate to
# every edge node, so an immediate request may 401 — retry a few times.
seed_env() { # $1=url $2=token $3...=extra seed_d1.py args
  local url="$1" token="$2"; shift 2
  local attempt
  for attempt in 1 2 3 4 5; do
    if WORKER_URL="$url" WORKER_AUTH_TOKEN="$token" uv run python scripts/seed_d1.py "$@"; then
      return 0
    fi
    echo "    (attempt $attempt/5 failed — secret may still be propagating, retrying in 5s)"
    sleep 5
  done
  return 1
}

if [[ -n "$WORKER_URL" ]]; then
  seed_env "$WORKER_URL" "$WORKER_AUTH_TOKEN" \
    || echo "    ! Prod seeding incomplete — if you haven't done OAuth yet, run 'uv run spotify-mcp setup' once, then rerun this script."
else
  echo "    ! Prod seed skipped (Worker URL unknown) — run scripts/seed_d1.py manually."
fi

echo
echo "============================================================"
echo "Setup done: D1 database \"$PROD_DB\", Worker deployed — hourly cron is live."

cat <<'EOF'

Next:
  - Nothing — the Worker cron is already live (hourly at :07); first sync
    within the hour. Health: Cloudflare dashboard -> Worker -> Cron Events.
  - Optional dry-run without waiting: docs/DEPLOY.md "Dry-run" section.
============================================================
EOF
