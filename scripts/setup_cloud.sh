#!/usr/bin/env bash
# One-time Cloudflare setup for the D1-backed deployment (docs/DEPLOY.md),
# Creates the prod + test D1 databases, applies the Worker's migrations,
# deploys the Worker to both environments, and (if gh is available) writes the GitHub
# Actions secrets sync.yml/sync-test.yml needed.
#
# Usage:
#   bash scripts/setup_cloud.sh <worker-auth-token> <worker-test-auth-token> [r2-backup-bucket]
#
# Examples:
#   bash scripts/setup_cloud.sh $(openssl rand -hex 32) $(openssl rand -hex 32)
#   bash scripts/setup_cloud.sh "$PROD_TOKEN" "$TEST_TOKEN" spotify-analytics-backup
#
# With gh logged in, this script does EVERYTHING: Cloudflare infra and all GitHub Actions secrets.
# Every step is idempotent, rerunning is always safe (e.g. after rotating a token or re-deploying the Worker).
#
# Requires: node/npx (wrangler), gh (GitHub CLI) recommended for the secrets step.

set -euo pipefail

WORKER_AUTH_TOKEN="${1:?usage: setup_cloud.sh <worker-auth-token> <worker-test-auth-token> [r2-backup-bucket]}"
WORKER_TEST_AUTH_TOKEN="${2:?usage: setup_cloud.sh <worker-auth-token> <worker-test-auth-token> [r2-backup-bucket]}"
R2_BACKUP_BUCKET="${3:-spotify-analytics-backup}"

PROD_DB="spotify-analytics"
TEST_DB="spotify-analytics-test"
WRANGLER="npx --yes wrangler@4"
WORKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../worker" && pwd)"

echo "==> [1/5] Cloudflare login (opens a browser the first time)"
(cd "$WORKER_DIR" && $WRANGLER whoami) || (cd "$WORKER_DIR" && $WRANGLER login)

echo "==> [2/6] D1 databases: $PROD_DB, $TEST_DB"
(cd "$WORKER_DIR" && $WRANGLER d1 create "$PROD_DB") \
  || echo "    $PROD_DB exists already — fine, continuing"
(cd "$WORKER_DIR" && $WRANGLER d1 create "$TEST_DB") \
  || echo "    $TEST_DB exists already — fine, continuing"

echo "==> [2b/6] Patching worker/wrangler.toml with real database_id values"
D1_LIST_JSON="$(cd "$WORKER_DIR" && $WRANGLER d1 list --json)"
python3 - "$WORKER_DIR/wrangler.toml" "$PROD_DB" "$TEST_DB" <<PYEOF
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

echo "==> [3/6] R2 backup bucket: $R2_BACKUP_BUCKET"
(cd "$WORKER_DIR" && $WRANGLER r2 bucket create "$R2_BACKUP_BUCKET") \
  || echo "    bucket exists already — fine, continuing"

echo "==> [4/6] Apply migrations + deploy the Worker (prod + test)"
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

echo "==> [4b/6] Worker-side AUTH_TOKEN secrets (prod + test) — never printed"
printf '%s' "$WORKER_AUTH_TOKEN" | (cd "$WORKER_DIR" && $WRANGLER secret put AUTH_TOKEN)
printf '%s' "$WORKER_TEST_AUTH_TOKEN" | (cd "$WORKER_DIR" && $WRANGLER secret put AUTH_TOKEN --env test)

# ---------------------------------------------------------------------------
# GitHub Actions secrets — via gh, if available.
# ---------------------------------------------------------------------------
MISSING_SECRETS=()
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "==> [5/6] Setting GitHub Actions secrets via gh (values are never printed)"
  gh secret set WORKER_AUTH_TOKEN --body "$WORKER_AUTH_TOKEN"
  gh secret set WORKER_TEST_AUTH_TOKEN --body "$WORKER_TEST_AUTH_TOKEN"
  gh secret set R2_BACKUP_BUCKET --body "$R2_BACKUP_BUCKET"

  if [[ -n "$WORKER_URL" ]]; then
    gh secret set WORKER_URL --body "$WORKER_URL"
    gh secret set WORKER_TEST_URL --body "$WORKER_TEST_URL"
  else
    MISSING_SECRETS+=("WORKER_URL" "WORKER_TEST_URL")
  fi

  ENV_FILE=""
  for cand in "./.env" "./data/.env"; do
    [[ -f "$cand" ]] && { ENV_FILE="$cand"; break; }
  done
  for name in SPOTIFY_CLIENT_ID TOKEN_ENCRYPT_KEY CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN; do
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
  GH_DONE=1
else
  GH_DONE=0
fi

echo
echo "============================================================"
echo "Setup done: D1 databases \"$PROD_DB\" + \"$TEST_DB\", Worker deployed."

if [[ "$GH_DONE" != "1" ]]; then
  cat <<EOF

! GitHub secrets NOT set — gh is missing or not logged in. Run 'gh auth login'
  and rerun this script, or add these by hand in GitHub -> repo Settings ->
  Secrets and variables -> Actions:
     WORKER_URL   WORKER_AUTH_TOKEN   WORKER_TEST_URL   WORKER_TEST_AUTH_TOKEN
     R2_BACKUP_BUCKET   SPOTIFY_CLIENT_ID   TOKEN_ENCRYPT_KEY
     CLOUDFLARE_ACCOUNT_ID   CLOUDFLARE_API_TOKEN
EOF
elif [[ ${#MISSING_SECRETS[@]} -gt 0 ]]; then
  cat <<EOF

! Could not auto-fill these secrets — set them yourself (gh prompts for the
  value, nothing is echoed):
EOF
  for name in "${MISSING_SECRETS[@]}"; do
    echo "     gh secret set $name"
  done
  echo "   (SPOTIFY_CLIENT_ID / TOKEN_ENCRYPT_KEY / CLOUDFLARE_ACCOUNT_ID /"
  echo "    CLOUDFLARE_API_TOKEN live in the wizard's .env)"
else
  echo "All GitHub Actions secrets are set."
fi

cat <<'EOF'

Next:
  - One-time backfill (production R2 -> D1): scripts/migrate_r2_to_d1.py)
  - Dry-run the pipeline:  gh workflow run sync-test && gh run watch
    (runs against the throwaway spotify-analytics-test D1 database)
  - Go live: merge to main. The hourly cron in sync.yml only fires from the
    default branch; first run within the hour (at :23).
============================================================
EOF
