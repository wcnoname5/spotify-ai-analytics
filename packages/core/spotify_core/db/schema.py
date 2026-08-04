"""SQLite DDL, loaded from the numbered migrations in ``db/sql/migrations/``.

Those files are the single source of schema truth, applied to all three targets:

- Cloudflare D1, embedded by ``apps/tauri/src-tauri/src/cloudflare.rs``
- the app's local cache, by ``apps/tauri/src/lib/migrations.ts``
- here, for Python's own DB creation

There used to be two copies — ``db/sql/schema.sql`` and ``worker/migrations/``,
the latter opening with "Copied from schema.sql". Keeping two hand-maintained
copies of the same DDL in step is exactly the drift this repo keeps getting bitten
by, so schema.sql is gone.
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


# Kept as module-level names because callers import them directly. Both are the
# full set now: `spotify_tokens` is in 0001, so there is no history/tokens split.
ALL_DDL = all_ddl()
HISTORY_DDL = ALL_DDL

SPOTIFY_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS spotify_tokens (
    user_id       TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    DATETIME NOT NULL,
    scopes        TEXT
);
"""
