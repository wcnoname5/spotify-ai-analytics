"""Bump the version field in all three pyproject.toml files.

Usage:
    uv run python scripts/bump.py 0.2.0        # set explicit version
    uv run python scripts/bump.py 0.2.0rc1     # pre-release (TestPyPI only)
    uv run python scripts/bump.py              # auto-bump patch (x.y.Z -> x.y.Z+1)

The script only rewrites the top-level [project] version field. It does not
commit or tag — do that manually after reviewing the diff.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOML_PATHS = [
    REPO_ROOT / "packages" / "core" / "pyproject.toml",
    REPO_ROOT / "packages" / "dataloader" / "pyproject.toml",
    REPO_ROOT / "apps" / "mcp" / "pyproject.toml",
]

VERSION_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.MULTILINE)
PEP440_RE = re.compile(r"^\d+\.\d+\.\d+([abc]|rc|\.dev|\.post)?\d*$")


def read_current(path: Path) -> str:
    match = VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"no version field found in {path}")
    return match.group(2)


def bump_patch(version: str) -> str:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not m:
        raise SystemExit(
            f"cannot auto-bump pre-release/non-standard version '{version}' — "
            f"pass an explicit version argument instead."
        )
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def write_version(path: Path, new_version: str) -> str:
    text = path.read_text(encoding="utf-8")
    new_text, count = VERSION_RE.subn(
        lambda m: f'{m.group(1)}{new_version}{m.group(3)}', text, count=1
    )
    if count != 1:
        raise SystemExit(f"failed to update version in {path}")
    path.write_text(new_text, encoding="utf-8")
    return new_text


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit("usage: bump.py [NEW_VERSION]")

    current_versions = {p: read_current(p) for p in TOML_PATHS}
    distinct = set(current_versions.values())
    if len(distinct) > 1:
        print("warning: pyproject.toml files are not at the same version:")
        for p, v in current_versions.items():
            print(f"  {p.relative_to(REPO_ROOT)}: {v}")

    if len(sys.argv) == 2:
        new_version = sys.argv[1].lstrip("v")
        if not PEP440_RE.match(new_version):
            raise SystemExit(
                f"'{new_version}' doesn't look like a PEP 440 version "
                f"(expected like 0.2.0, 0.2.0rc1, 0.2.0a1, 0.2.0.dev1)."
            )
    else:
        new_version = bump_patch(next(iter(distinct)))

    for path in TOML_PATHS:
        old = current_versions[path]
        write_version(path, new_version)
        print(f"  {path.relative_to(REPO_ROOT)}: {old} -> {new_version}")

    print(f"\nbumped to {new_version}. Next steps:")
    print(f'  git commit -am "chore: bump version to {new_version}"')
    print(f"  git tag v{new_version}")
    print("  git push && git push --tags")


if __name__ == "__main__":
    main()
