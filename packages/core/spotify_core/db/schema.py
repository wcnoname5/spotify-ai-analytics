"""SQLite DDL, loaded from the numbered migrations in ``db/sql/migrations/``.

Those files are the single source of schema truth:

- Cloudflare D1, embedded by ``apps/tauri/src-tauri/src/cloudflare.rs``
- the app's local cache, by ``apps/tauri/src/lib/migrations.ts``
- here, for the test suite's throwaway databases
"""
from importlib.resources import files


def migrations() -> list[tuple[str, str]]:
    """``(filename, sql)`` for every migration, in filename order.

    Filename order *is* apply order — that is what the numeric prefix is for, and
    what ``PRAGMA user_version`` counts.
    """
    directory = files("spotify_core.db.sql").joinpath("migrations")
    names = sorted(p.name for p in directory.iterdir() if p.name.endswith(".sql"))
    return [(name, directory.joinpath(name).read_text(encoding="utf-8")) for name in names]


def statements(sql: str) -> list[str]:
    """Split one migration into statements.

    Comments are stripped first because they contain semicolons. This is a naive
    split and stays correct only while migrations hold plain DDL — a trigger body
    or a string literal containing `;` would break it, and is the point at which
    this needs a real parser rather than a slightly cleverer regex.
    """
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in code.split(";") if s.strip()]


def all_ddl() -> list[str]:
    """Every statement from every migration, in order."""
    return [stmt for _, sql in migrations() for stmt in statements(sql)]
