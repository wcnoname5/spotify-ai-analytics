"""Generate worker/migrations/0001_init.sql from spotify_core.db.schema.ALL_DDL.

Manually-rerun dev tool (not part of CI): whenever schema.py changes, rerun this
to regenerate the D1 migration so the Worker's schema stays in sync with the
Python source of truth.

Usage:
    uv run python scripts/gen_d1_migration.py
"""

from pathlib import Path

from spotify_core.db.schema import ALL_DDL

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "worker" / "migrations" / "0001_init.sql"


def main() -> None:
    statements = [ddl.strip() for ddl in ALL_DDL]
    header = "-- Generated from packages/core/spotify_core/db/schema.py (ALL_DDL). Do not edit by hand.\n-- Regenerate with: uv run python scripts/gen_d1_migration.py\n"
    content = header + "\n\n".join(statements) + "\n"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
