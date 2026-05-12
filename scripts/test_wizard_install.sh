#!/usr/bin/env bash
# Build all wheels and run the wizard tests in a clean, isolated environment.
# The clean venv holds only the installed packages + pytest — no workspace editable installs.
#
# Usage:
#   bash scripts/test_wizard_install.sh          # build + test
#   bash scripts/test_wizard_install.sh --clean  # also remove the venv afterwards

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
TEST_VENV="$REPO_ROOT/.venv-wizard-test"
CLEAN_UP=0
[[ "${1:-}" == "--clean" ]] && CLEAN_UP=1

step() { echo; echo "━━━  $*  ━━━"; }
ok()   { echo "✓  $*"; }
fail() { echo "✗  $*" >&2; exit 1; }

# ── 1. Build wheels ───────────────────────────────────────────────────────────
step "Building wheels"
rm -rf "$DIST_DIR"
uv build "$REPO_ROOT/packages/core"       --out-dir "$DIST_DIR"
uv build "$REPO_ROOT/packages/dataloader" --out-dir "$DIST_DIR"
uv build "$REPO_ROOT/apps/mcp"            --out-dir "$DIST_DIR"
WHEELS=("$DIST_DIR"/*.whl)
[[ ${#WHEELS[@]} -eq 0 ]] && fail "No wheels found in $DIST_DIR"
ok "Built ${#WHEELS[@]} wheel(s):"
for w in "${WHEELS[@]}"; do echo "     $(basename "$w")"; done

# ── 2. Create clean venv ──────────────────────────────────────────────────────
step "Creating clean venv"
rm -rf "$TEST_VENV"
uv venv "$TEST_VENV"
ok "Venv at $TEST_VENV"

# Resolve bin dir (Unix → bin/, Windows Git Bash → Scripts/)
if [[ -d "$TEST_VENV/Scripts" ]]; then
    BIN="$TEST_VENV/Scripts"
else
    BIN="$TEST_VENV/bin"
fi

# ── 3. Install wheels + pytest ────────────────────────────────────────────────
step "Installing packages"
uv pip install --python "$TEST_VENV" "${WHEELS[@]}" pytest
ok "Installed $(uv pip list --python "$TEST_VENV" | wc -l) packages"

# ── 4. Verify CLI entry point ─────────────────────────────────────────────────
step "Verifying spotify-mcp CLI"
[[ -x "$BIN/spotify-mcp" ]] || fail "spotify-mcp binary not found in $BIN"
"$BIN/spotify-mcp" --help
ok "CLI smoke test passed"

# ── 5. Run wizard tests ───────────────────────────────────────────────────────
step "Running wizard tests"
"$BIN/pytest" "$REPO_ROOT/tests/mcp/" -v --no-header -p no:cacheprovider \
    --tb=short 2>&1
ok "Wizard tests complete"

# ── Cleanup (optional) ────────────────────────────────────────────────────────
if [[ $CLEAN_UP -eq 1 ]]; then
    step "Cleaning up"
    rm -rf "$TEST_VENV" "$DIST_DIR"
    ok "Removed $TEST_VENV and $DIST_DIR"
fi

echo
echo "Done. To inspect: source $BIN/activate && spotify-mcp --help"
