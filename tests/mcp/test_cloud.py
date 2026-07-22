"""The bits of `spotify_mcp.cloud` that are not just wrangler plumbing.

`_render_config` is the piece that replaced in-place patching of
worker/wrangler.toml; if it silently stopped substituting, a `--name` test
deploy would target the production database.
"""
import sqlite3
import tomllib

import pytest

from spotify_mcp import cloud, seed


def test_render_config_targets_the_named_stack():
    path = cloud._render_config("spotify-analytics-test", "abc-123")
    try:
        conf = tomllib.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink()

    assert conf["name"] == "spotify-analytics-test-worker"
    db = conf["d1_databases"][0]
    assert db["database_name"] == "spotify-analytics-test"
    assert db["database_id"] == "abc-123"
    # The cron is the whole point of deploying; losing it would be silent.
    assert conf["triggers"]["crons"] == ["7 * * * *"]


@pytest.mark.parametrize("initialised", [False, True])
def test_local_token_row_is_none_before_oauth(monkeypatch, tmp_path, initialised):
    """Deploying before authorizing is a legitimate order — it must not raise.

    An uninitialised tokens.db has no `spotify_tokens` table at all, which
    raises OperationalError rather than returning no row.
    """
    db = tmp_path / "tokens.db"
    if initialised:
        sqlite3.connect(db).close()
    monkeypatch.setattr(seed.settings, "tokens_db_path", db)

    assert seed.local_token_row("default") is None


def test_seed_reports_worker_failure_as_a_return_code(monkeypatch):
    """A 401 right after deploy is the retry loop's whole reason to exist.

    Worker calls raise on non-2xx, so if that escapes instead of returning
    non-zero, deploy() aborts on the one failure it was built to survive.
    """
    import spotify_core.db.worker_client as wc

    class Boom:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_tokens(self, _user): raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(wc, "WorkerClient", Boom)

    assert cloud.seed(worker_url="https://example.workers.dev", worker_token="t") == 1


def test_pull_without_a_worker_is_a_return_code(monkeypatch, tmp_path):
    """No Worker configured is a normal local-only state, not a crash.

    `serve` calls this on startup, so raising here would stop the MCP server
    from booting for anyone who never set up cloud sync.
    """
    monkeypatch.setattr(cloud.paths, "env_file", lambda: tmp_path / ".env")

    assert cloud.pull(quiet=True) == 1


def test_pull_reports_worker_failure_as_a_return_code(monkeypatch):
    """Same contract as seed: an unreachable Worker must not escape as an exception."""
    import spotify_core.db.worker_client as wc

    class Boom:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(wc, "WorkerClient", Boom)
    monkeypatch.setattr(
        "spotify_core.db.local_sync.run_local_sync",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )

    assert cloud.pull(worker_url="https://example.workers.dev", worker_token="t", quiet=True) == 1


def test_render_config_leaves_the_repo_toml_alone():
    """A test deploy must not leave state a later prod deploy would pick up."""
    real = cloud.worker_dir() / "wrangler.toml"
    before = real.read_text(encoding="utf-8") if real.exists() else None

    cloud._render_config("spotify-analytics-test", "abc-123").unlink()

    after = real.read_text(encoding="utf-8") if real.exists() else None
    assert after == before
