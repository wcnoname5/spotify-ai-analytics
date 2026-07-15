#!/usr/bin/env bash
# One-time Cloudflare setup for the D1-backed deployment (docs/DEPLOY.md),
# Creates the prod + test D1 databases, applies the Worker's migrations,
# deploys the Worker to both environments, and (if gh is available) writes the GitHub
# Actions secrets sync.yml/sync-test.yml needed.
#
# Usage:
#   bash scripts/setup_cloud.sh [worker-auth-token] [worker-test-auth-token]
#
# Requires: node/npx (wrangler), gh (GitHub CLI).

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
WORKER_TEST_AUTH_TOKEN="${2:-$(gen_hex)}"

PROD_DB="spotify-analytics"
TEST_DB="spotify-analytics-test"
WRANGLER="npx --yes wrangler@4"
WORKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../worker" && pwd)"

# ---------------------------------------------------------------------------
# [0/5] .env: ensure SPOTIFY_CLIENT_ID (prompt) and TOKEN_ENCRYPT_KEY (generate).
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

echo "==> [0/5] Checking $ENV_FILE"
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

echo "==> [1/5] Cloudflare login (opens a browser the first time)"
(cd "$WORKER_DIR" && $WRANGLER whoami) || (cd "$WORKER_DIR" && $WRANGLER login)

echo "==> [2/5] D1 databases: $PROD_DB, $TEST_DB"
(cd "$WORKER_DIR" && $WRANGLER d1 create "$PROD_DB") \
  || echo "    $PROD_DB exists already — fine, continuing"
(cd "$WORKER_DIR" && $WRANGLER d1 create "$TEST_DB") \
  || echo "    $TEST_DB exists already — fine, continuing"

echo "==> [2b/5] Patching worker/wrangler.toml with real database_id values"
[[ -f "$WORKER_DIR/wrangler.toml" ]] || cp "$WORKER_DIR/wrangler.toml.example" "$WORKER_DIR/wrangler.toml"
D1_LIST_JSON="$(cd "$WORKER_DIR" && $WRANGLER d1 list --json)"
$PYTHON - "$WORKER_DIR/wrangler.toml" "$PROD_DB" "$TEST_DB" <<PYEOF
import json, re, sys
toml_path, prod_name, test_name = sys.argv[1:4]
databases = json.loads('''$D1_LIST_JSON''')
by_name = {d["name"]: d["uuid"] for d in databases}
prod_id = by_name[prod_name]
test_id = by_name[test_name]

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
text = patch(text, test_name, test_id)
open(toml_path, "w", encoding="utf-8").write(text)
print(f"    {prod_name} -> {prod_id}")
print(f"    {test_name} -> {test_id}")
PYEOF

echo "==> [3/5] Apply migrations + deploy the Worker (prod + test)"
(cd "$WORKER_DIR" && $WRANGLER d1 migrations apply "$PROD_DB" --remote)
(cd "$WORKER_DIR" && $WRANGLER d1 migrations apply "$TEST_DB" --env test --remote)
DEPLOY_OUT="$(cd "$WORKER_DIR" && $WRANGLER deploy)"
echo "$DEPLOY_OUT"
WORKER_URL="$(echo "$DEPLOY_OUT" | grep -oE 'https://[^ ]+\.workers\.dev' | head -1 || true)"

DEPLOY_TEST_OUT="$(cd "$WORKER_DIR" && $WRANGLER deploy --env test)"
echo "$DEPLOY_TEST_OUT"
WORKER_TEST_URL="$(echo "$DEPLOY_TEST_OUT" | grep -oE 'https://[^ ]+\.workers\.dev' | head -1 || true)"

if [[ -z "$WORKER_URL" || -z "$WORKER_TEST_URL" ]]; then
  echo "    warning: could not parse the Worker URL(s) from the deploy output —"
  echo "    set WORKER_URL/WORKER_TEST_URL manually (GitHub -> repo Settings ->"
  echo "    Secrets and variables -> Actions)."
fi

echo "==> [3b/5] Worker-side AUTH_TOKEN secrets (prod + test) — never printed"
printf '%s' "$WORKER_AUTH_TOKEN" | (cd "$WORKER_DIR" && $WRANGLER secret put AUTH_TOKEN)
printf '%s' "$WORKER_TEST_AUTH_TOKEN" | (cd "$WORKER_DIR" && $WRANGLER secret put AUTH_TOKEN --env test)

# Write WORKER_* to .env, OVERWRITING stale values: each run without args
# rotates the Bearer token on the Worker and in GitHub secrets, so a
# leftover old value in .env would 401 every local script.
[[ -n "$WORKER_URL" ]] && env_set WORKER_URL "$WORKER_URL"
env_set WORKER_AUTH_TOKEN "$WORKER_AUTH_TOKEN"

# ---------------------------------------------------------------------------
# GitHub Actions secrets — via gh, if available.
# ---------------------------------------------------------------------------
MISSING_SECRETS=()
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "==> [4/5] Setting GitHub Actions secrets via gh (values are never printed)"
  gh secret set WORKER_AUTH_TOKEN --body "$WORKER_AUTH_TOKEN"
  gh secret set WORKER_TEST_AUTH_TOKEN --body "$WORKER_TEST_AUTH_TOKEN"

  if [[ -n "$WORKER_URL" ]]; then
    gh secret set WORKER_URL --body "$WORKER_URL"
    gh secret set WORKER_TEST_URL --body "$WORKER_TEST_URL"
  else
    MISSING_SECRETS+=("WORKER_URL" "WORKER_TEST_URL")
  fi

  for name in SPOTIFY_CLIENT_ID TOKEN_ENCRYPT_KEY; do
    val="$(env_get "$name")"
    if [[ -n "$val" ]]; then
      gh secret set "$name" --body "$val"
    else
      MISSING_SECRETS+=("$name")
    fi
  done
  GH_DONE=1
else
  GH_DONE=0
fi

echo "==> [5/5] Seeding D1 (prod: tokens + history; test: tokens only) — skips whatever D1 already has"
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
if [[ -n "$WORKER_TEST_URL" ]]; then
  # Test D1 needs a token row too or sync-test can never pass; history would
  # just waste free-tier writes on a throwaway DB.
  seed_env "$WORKER_TEST_URL" "$WORKER_TEST_AUTH_TOKEN" --tokens-only \
    || echo "    ! Test-env token seed failed — sync-test will fail until this succeeds."
else
  echo "    ! Test seed skipped (test Worker URL unknown)."
fi

echo
echo "============================================================"
echo "Setup done: D1 databases \"$PROD_DB\" + \"$TEST_DB\", Worker deployed."

if [[ "$GH_DONE" != "1" ]]; then
  cat <<EOF

! GitHub secrets NOT set — gh is missing or not logged in. Run 'gh auth login'
  and rerun this script.
EOF
elif [[ ${#MISSING_SECRETS[@]} -gt 0 ]]; then
  cat <<EOF

! Could not auto-fill these secrets — set them yourself (gh prompts for the
  value, nothing is echoed):
EOF
  for name in "${MISSING_SECRETS[@]}"; do
    echo "     gh secret set $name"
  done
else
  echo "All GitHub Actions secrets are set."
fi

cat <<'EOF'

Next:
  - Dry-run the pipeline:  gh workflow run sync-test && gh run watch
    (runs against the throwaway spotify-analytics-test D1 database)
  - Go live: merge to main. The hourly cron in sync.yml only fires from the
    default branch; first run within the hour (at :23).
============================================================
EOF
