#!/usr/bin/env bash
# Build all wheels and run the wizard tests in a clean, isolated environment.
# The clean venv holds only the installed packages + pytest — no workspace editable installs.
#
# Usage:
#   bash scripts/test_wizard_install.sh           # build + test
#   bash scripts/test_wizard_install.sh --fresh   # also run CLI smoke tests against an isolated, empty config/data dir
#   bash scripts/test_wizard_install.sh --clean   # also remove the venv + dist afterwards
#
# Flags can be combined: --fresh --clean

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
TEST_VENV="$REPO_ROOT/.venv-wizard-test"
FRESH_STATE="$REPO_ROOT/.wizard-test-state"

CLEAN_UP=0
FRESH=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN_UP=1 ;;
        --fresh) FRESH=1 ;;
        *) echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

step() { echo; echo "━━━  $*  ━━━"; }
ok()   { echo "✓  $*"; }
warn() { echo "⚠  $*" >&2; }
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

# ── 6. Fresh CLI smoke (optional) ─────────────────────────────────────────────
# Isolate from the real user config/data dirs by pointing the path resolver
# (packages/core/spotify_core/paths.py) at a throwaway directory. This mimics
# a brand-new user with no existing .env, no tokens.db, no history.db.
if [[ $FRESH -eq 1 ]]; then
    step "Fresh CLI smoke tests (isolated state)"

    rm -rf "$FRESH_STATE"
    mkdir -p "$FRESH_STATE/cfg" "$FRESH_STATE/data"

    # Subshell so env overrides don't leak.
    (
        export SPOTIFY_MCP_CONFIG_DIR="$FRESH_STATE/cfg"
        export SPOTIFY_MCP_DATA_DIR="$FRESH_STATE/data"
        # Also unset any inherited creds — a real fresh user has none.
        unset SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET TOKEN_ENCRYPT_KEY SPOTIFY_USER_ID

        CLI="$BIN/spotify-mcp"

        # Helper: run a command, allow non-zero exit, but fail if Python traceback appears.
        # $1 = label, rest = command + args
        run_check() {
            local label="$1"; shift
            echo
            echo "── $label ── \$ $*"
            local out rc
            out="$("$@" 2>&1)" && rc=0 || rc=$?
            echo "$out"
            if echo "$out" | grep -qE "^Traceback|Error: Internal|Unhandled exception"; then
                fail "$label: unhandled exception (see traceback above)"
            fi
            echo "   → exit $rc"
            FRESH_LAST_RC=$rc
            FRESH_LAST_OUT="$out"
        }

        # a) --help must succeed
        run_check "spotify-mcp --help" "$CLI" --help
        [[ $FRESH_LAST_RC -eq 0 ]] || fail "--help exited $FRESH_LAST_RC"

        # b) doctor must run and report not-ready (exit 1) — proves our env overrides bit
        run_check "spotify-mcp doctor" "$CLI" doctor
        if [[ $FRESH_LAST_RC -eq 0 ]]; then
            fail "doctor reported ready against an empty config dir — env overrides are NOT taking effect (would have touched real user state)"
        fi
        echo "$FRESH_LAST_OUT" | grep -q '"ready"' \
            || fail "doctor output missing 'ready' field — JSON shape changed?"

        # c) Subcommand --help screens (catches import-time errors in each module)
        for sub in setup doctor reauth sync serve; do
            run_check "spotify-mcp $sub --help" "$CLI" "$sub" --help
            [[ $FRESH_LAST_RC -eq 0 ]] || fail "$sub --help exited $FRESH_LAST_RC"
        done

        # d) sync without creds must fail cleanly (exit 1, no traceback)
        run_check "spotify-mcp sync (no creds)" "$CLI" sync
        [[ $FRESH_LAST_RC -ne 0 ]] || fail "sync unexpectedly succeeded without credentials"

        # e) serve startup smoke: launch, give it a moment, ensure it didn't die on import.
        #    We can't drive stdio MCP from bash, so just check the process is alive briefly.
        echo
        echo "── serve startup probe ──"
        "$CLI" serve >/tmp/spotify-mcp-serve.out 2>&1 &
        SERVE_PID=$!
        sleep 1.5
        if kill -0 "$SERVE_PID" 2>/dev/null; then
            kill "$SERVE_PID" 2>/dev/null || true
            wait "$SERVE_PID" 2>/dev/null || true
            ok "serve stayed up for >1s (no immediate crash)"
        else
            wait "$SERVE_PID" 2>/dev/null || true
            cat /tmp/spotify-mcp-serve.out >&2 || true
            fail "serve exited immediately — see output above"
        fi

        # f) Confirm no leakage into the real user dirs: nothing should have been written
        #    outside $FRESH_STATE. (We only assert OUR overrides got used by checking that
        #    doctor stayed not-ready, above. A full leak check would require knowing the
        #    user's real platformdirs path; skip it.)
        ok "All fresh CLI smoke checks passed (state lived under $FRESH_STATE)"
    )
fi

# ── Cleanup (optional) ────────────────────────────────────────────────────────
if [[ $CLEAN_UP -eq 1 ]]; then
    step "Cleaning up"
    rm -rf "$TEST_VENV" "$DIST_DIR" "$FRESH_STATE"
    ok "Removed $TEST_VENV, $DIST_DIR$([[ $FRESH -eq 1 ]] && echo ", $FRESH_STATE")"
fi

echo
echo "Done. To inspect: source $BIN/activate && spotify-mcp --help"
if [[ $FRESH -eq 1 && $CLEAN_UP -eq 0 ]]; then
    echo "Fresh state preserved at: $FRESH_STATE"
fi
