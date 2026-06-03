---
name: release-to-pypi
description: Use when releasing or publishing the spotify-analytics-* packages — bumping the version, cutting a release-candidate (rc) tag, verifying on TestPyPI, and promoting to a stable PyPI release. Triggers on "release", "publish", "cut a release", "bump version", "ship a new version", "push to PyPI/TestPyPI".
---

# Release to PyPI (rc-first)

This repo publishes three packages — `spotify-analytics-core`, `spotify-analytics-dataloader`,
`spotify-analytics-mcp` — via the tag-driven GitHub Actions workflow `.github/workflows/publish.yaml`
(OIDC trusted publishers). **You never run `twine` or `uv publish` locally.** You bump versions,
push a git tag, and CI does the upload.

Throughout this runbook `X.Y.Z` is the target version (e.g. the next release) — substitute the real
number. Pre-release suffixes are `rcN` / `aN` / `bN` / `.devN`.

## The rule the workflow enforces

- A **pre-release** tag (PEP 440 suffix matching `(a|b|rc|\.dev)[0-9]+$`, e.g. `vX.Y.Zrc1`) publishes
  to **TestPyPI only**.
- A **stable** tag (e.g. `vX.Y.Z`) publishes to **TestPyPI *and* PyPI** (`pypi-mcp` runs after
  `pypi-core` + `pypi-dataloader` so the mcp package's runtime deps resolve).

So the release path is always: **rc → verify on TestPyPI → stable.**

## Safety gates (do NOT skip)

- Pushing a tag triggers a public publish. **Always confirm with the user before `git push --tags`.**
- A version number can be uploaded to (Test)PyPI exactly once. If an rc is broken, **bump the rc
  number** (`rc2`), never reuse it.
- Work from a clean tree. Stable releases happen from `main`.

---

## Stage 0 — Pre-flight

```bash
git status                       # clean tree, on the intended branch
uv run pytest                    # full suite green
```

Read the current version from any pyproject and confirm all three match (the bump script warns if they
diverge). Confirm the mcp wheel still bundles the Streamlit dashboard UI (it lives under
`spotify_mcp/dashboard/` and the wheel packages the whole `spotify_mcp` import package):

```bash
uv build --package spotify-analytics-mcp --wheel
python -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('dist/spotify_analytics_mcp-*.whl')[0]); print('\n'.join(n for n in z.namelist() if 'dashboard' in n))"
rm -rf dist
```

Expect to see `spotify_mcp/dashboard/...` including `spotify_mcp/dashboard/main_page.py`. If absent,
stop — the `[dashboard]` extra will be broken on install.

## Stage 1 — Bump and cut the release candidate (→ TestPyPI)

`scripts/bump.py` is the single source of truth for the version: it rewrites the `[project]` version
in all three `pyproject.toml`s and keeps them equal. It does **not** commit, tag, or push. Pass the
explicit version with the `rc` suffix (auto-bump can't produce pre-releases — see Gotchas):

```bash
uv run python scripts/bump.py X.Y.Zrc1
git diff                                  # confirm all three pyproject.toml changed
git commit -am "chore: bump version to X.Y.Zrc1"
git tag vX.Y.Zrc1
```

**Before pushing, clean-room check the runtime deps.** The `--version` / dashboard-launch checks in
Stage 2 don't exercise the report path, so a missing *report* dependency (e.g. langfuse's
`langfuse.langchain` does a bare `import langchain`) only surfaces when a report is actually generated
— and by then the rc number is already burned. Build local wheels at the rc version and import the
report path in a throwaway venv (our three packages come from the local dist, transitive deps resolve
from real PyPI):

```bash
uv build --all-packages --out-dir dist/
uv venv .relcheck --python 3.12
uv pip install --python .relcheck --find-links dist/ --prerelease=allow \
  "spotify-analytics-mcp[dashboard]==X.Y.Zrc1" "spotify-analytics-core==X.Y.Zrc1" "spotify-analytics-dataloader==X.Y.Zrc1"
# venv python: .relcheck/Scripts/python on Windows, .relcheck/bin/python on macOS/Linux
.relcheck/Scripts/python -c "from langfuse.langchain import CallbackHandler; from spotify_core.report.observability import langfuse_session; import spotify_mcp; print('report path OK')"
rm -rf dist .relcheck
```

Only once that prints `report path OK`, push (this triggers the publish):

```bash
# CONFIRM WITH USER, then:
git push && git push --tags
```

Watch CI; it should run the `testpypi-*` jobs and **skip** the `pypi-*` jobs:

```bash
gh run watch
```

## Stage 2 — Verify the rc on TestPyPI (via uvx)

TestPyPI lacks most transitive deps (fastmcp, streamlit, langchain, …), so point the primary index at
TestPyPI and let `unsafe-best-match` fall back to real PyPI. Pin all three packages to the rc version
(bump.py keeps them equal). Minimal core commands:

```bash
# Core CLI surface
uvx --refresh --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match --from "spotify-analytics-mcp==X.Y.Zrc1" --with "spotify-analytics-core==X.Y.Zrc1" --with "spotify-analytics-dataloader==X.Y.Zrc1" spotify-mcp --version

# Dashboard (needs the extra — confirms the bundled spotify_mcp/dashboard survives a real install)
uvx --refresh --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match --from "spotify-analytics-mcp[dashboard]==X.Y.Zrc1" --with "spotify-analytics-core==X.Y.Zrc1" --with "spotify-analytics-dataloader==X.Y.Zrc1" spotify-mcp dashboard
```

Launching the dashboard only hits the report path when you generate a report, so also do a
non-interactive import check against what's actually on TestPyPI (the published analogue of the
Stage 1 pre-push check):

```bash
uv venv .rccheck --python 3.12
uv pip install --python .rccheck --refresh --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match "spotify-analytics-mcp[dashboard]==X.Y.Zrc1" "spotify-analytics-core==X.Y.Zrc1" "spotify-analytics-dataloader==X.Y.Zrc1"
.rccheck/Scripts/python -c "from langfuse.langchain import CallbackHandler; from spotify_core.report.observability import langfuse_session; print('report path OK')"
rm -rf .rccheck
```

If something is broken: fix, bump to `X.Y.Zrc2`, re-tag, re-verify. Do not reuse `rc1`.

## Stage 3 — Promote to stable (→ PyPI)

Only after the rc passes verification, and from a clean `main`:

```bash
uv run python scripts/bump.py X.Y.Z
git commit -am "chore: bump version to X.Y.Z"
git tag vX.Y.Z
# CONFIRM WITH USER, then:
git push && git push --tags
gh run watch     # expect testpypi-* AND pypi-* jobs to run; pypi-mcp last
```

Verify the real release (no custom index needed once it's on PyPI):

```bash
uvx --refresh --from "spotify-analytics-mcp==X.Y.Z" spotify-mcp --version
uvx --refresh --from "spotify-analytics-mcp[dashboard]==X.Y.Z" spotify-mcp dashboard
```

## Bumping the version — quick reference

| Goal | Command |
|---|---|
| Set explicit stable version | `uv run python scripts/bump.py X.Y.Z` |
| Cut a release candidate | `uv run python scripts/bump.py X.Y.Zrc1` |
| Other pre-releases | `…/bump.py X.Y.Za1` · `X.Y.Zb2` · `X.Y.Z.dev1` |
| Auto-bump patch (Z+1) | `uv run python scripts/bump.py` *(no arg, stable only)* |

The version lives **only** in the three `pyproject.toml` `[project]` version fields — there is no
`__version__` constant and no dynamic/VCS versioning. Never hand-edit them; always use `scripts/bump.py`
so they stay in sync (the mcp package pins core/dataloader to the equal version).

## Gotchas

- `bump.py` with no arg auto-bumps the patch of a **stable** version only; it errors on an rc. Always
  pass the explicit version for rc steps.
- A leading `v` is accepted by `bump.py` (`v0.2.0` → `0.2.0`), but the input must be valid PEP 440
  (`X.Y.Z`, `X.Y.Zrc1`, `X.Y.Za1`, `X.Y.Z.dev1`). It rejects anything else.
- The CI prerelease regex is anchored at end-of-tag: `(a|b|rc|\.dev)[0-9]+$`. `vX.Y.Zrc1` matches;
  `vX.Y.Z-rc1` does NOT — don't add a hyphen.
- Tags drive routing, not the file version: a mismatch between your committed version and the tag will
  publish the wrong thing. Keep them identical (`bump.py X.Y.Z` → `git tag vX.Y.Z`).
- Six trusted publishers must already be registered (3 PyPI + 3 TestPyPI environments, named
  `pypi-{core,dataloader,mcp}` / `testpypi-{core,dataloader,mcp}`; see the header of
  `.github/workflows/publish.yaml`). If a publish job fails with an OIDC error, that registration is
  the cause — escalate to the user, don't try to work around it.
