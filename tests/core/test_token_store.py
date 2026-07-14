"""Unit tests for spotify_core.spotify_client.token_store."""
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from spotify_core.db.migrations import get_connection, init_db
from spotify_core.spotify_client.errors import SpotifyAuthError
from spotify_core.spotify_client.token_store import (
    delete_tokens,
    export_encrypted_row,
    import_encrypted_row,
    is_token_expired,
    load_tokens,
    save_tokens,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fernet_key() -> bytes:
    """Generate a fresh Fernet key for each test."""
    return Fernet.generate_key()


def _make_token_dict(expires_in: int = 3600, scope: str = "user-read-playback-state") -> dict:
    return {
        "access_token": "plain_access_token",
        "refresh_token": "plain_refresh_token",
        "expires_in": expires_in,
        "scope": scope,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_tokens_stores_encrypted_bytes(tmp_path):
    """save_tokens writes encrypted ciphertext, not plaintext, to the DB."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    save_tokens(db_path, "user1", _make_token_dict(), key)

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT access_token, refresh_token FROM spotify_tokens WHERE user_id = ?",
            ("user1",),
        ).fetchone()

    assert row is not None
    # Must NOT contain the plaintext token values.
    assert "plain_access_token" not in row["access_token"]
    assert "plain_refresh_token" not in row["refresh_token"]
    # Fernet ciphertext starts with 'g' (base64-encoded token).
    assert len(row["access_token"]) > 20
    assert len(row["refresh_token"]) > 20


@pytest.mark.unit
def test_load_tokens_returns_decrypted_values(tmp_path):
    """load_tokens returns the original plaintext tokens after save."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()
    token_dict = _make_token_dict(expires_in=3600, scope="streaming")

    save_tokens(db_path, "user1", token_dict, key)
    result = load_tokens(db_path, "user1", key)

    assert result is not None
    assert result["access_token"] == "plain_access_token"
    assert result["refresh_token"] == "plain_refresh_token"
    assert result["scopes"] == "streaming"
    # expires_at should be a datetime roughly 3600 seconds in the future.
    assert isinstance(result["expires_at"], datetime)
    now = datetime.now(timezone.utc)
    delta = result["expires_at"] - now
    assert 3500 < delta.total_seconds() < 3700


@pytest.mark.unit
def test_load_tokens_returns_none_when_not_found(tmp_path):
    """load_tokens returns None when the user has no stored tokens."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    result = load_tokens(db_path, "ghost_user", key)

    assert result is None


@pytest.mark.unit
def test_is_token_expired_true_for_expired_token(tmp_path):
    """is_token_expired returns True when expires_in is negative (already past)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    save_tokens(db_path, "user1", _make_token_dict(expires_in=-1), key)

    assert is_token_expired(db_path, "user1") is True


@pytest.mark.unit
def test_is_token_expired_false_for_fresh_token(tmp_path):
    """is_token_expired returns False when token expires well in the future."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    save_tokens(db_path, "user1", _make_token_dict(expires_in=3600), key)

    assert is_token_expired(db_path, "user1") is False


@pytest.mark.unit
def test_is_token_expired_true_when_user_not_found(tmp_path):
    """is_token_expired returns True when no row exists for the user."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    assert is_token_expired(db_path, "nonexistent_user") is True


@pytest.mark.unit
def test_delete_tokens_removes_row(tmp_path):
    """delete_tokens removes the row; subsequent load_tokens returns None."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    save_tokens(db_path, "user1", _make_token_dict(), key)
    assert load_tokens(db_path, "user1", key) is not None  # sanity

    delete_tokens(db_path, "user1")

    assert load_tokens(db_path, "user1", key) is None


@pytest.mark.unit
def test_save_tokens_overwrites_existing_row(tmp_path):
    """save_tokens with INSERT OR REPLACE: second save wins."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    # First save — different tokens.
    first_dict = {
        "access_token": "first_access",
        "refresh_token": "first_refresh",
        "expires_in": 3600,
        "scope": "old-scope",
    }
    save_tokens(db_path, "user1", first_dict, key)

    # Second save — should overwrite.
    second_dict = {
        "access_token": "second_access",
        "refresh_token": "second_refresh",
        "expires_in": 7200,
        "scope": "new-scope",
    }
    save_tokens(db_path, "user1", second_dict, key)

    result = load_tokens(db_path, "user1", key)
    assert result is not None
    assert result["access_token"] == "second_access"
    assert result["refresh_token"] == "second_refresh"
    assert result["scopes"] == "new-scope"

    # Ensure only one row exists.
    with get_connection(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM spotify_tokens WHERE user_id = ?", ("user1",)
        ).fetchone()[0]
    assert count == 1


@pytest.mark.unit
def test_delete_tokens_noop_when_user_not_found(tmp_path):
    """delete_tokens does not raise when no row exists for the user."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Should complete without error.
    delete_tokens(db_path, "nonexistent_user")


@pytest.mark.unit
def test_load_tokens_scope_empty_string_when_null(tmp_path):
    """load_tokens returns an empty string for scopes when the column is NULL."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    key = _make_fernet_key()

    # Insert a row with NULL scopes directly via raw SQL.
    f = Fernet(key)
    enc_access = f.encrypt(b"access_tok").decode()
    enc_refresh = f.encrypt(b"refresh_tok").decode()
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at, scopes) "
            "VALUES (?, ?, ?, ?, ?)",
            ("user_null_scope", enc_access, enc_refresh, expires_at, None),
        )
        conn.commit()

    result = load_tokens(db_path, "user_null_scope", key)
    assert result is not None
    assert result["scopes"] == ""


@pytest.mark.unit
def test_export_import_round_trip_still_decrypts(tmp_path):
    """export_encrypted_row/import_encrypted_row pass ciphertext through unchanged.

    A row exported from one DB and imported into another (scratch) DB must
    still decrypt correctly with the same Fernet key — the export/import
    path must never encrypt or decrypt, only move opaque ciphertext.
    """
    src_db = tmp_path / "src.db"
    dst_db = tmp_path / "dst.db"
    init_db(src_db)
    init_db(dst_db)
    key = _make_fernet_key()
    token_dict = _make_token_dict(expires_in=3600, scope="user-read-email")

    save_tokens(src_db, "user1", token_dict, key)

    exported = export_encrypted_row(src_db, "user1")
    assert exported is not None
    # Must be raw ciphertext, not plaintext.
    assert exported["access_token"] != "plain_access_token"
    assert exported["refresh_token"] != "plain_refresh_token"

    import_encrypted_row(dst_db, "user1", exported)

    result = load_tokens(dst_db, "user1", key)
    assert result is not None
    assert result["access_token"] == "plain_access_token"
    assert result["refresh_token"] == "plain_refresh_token"
    assert result["scopes"] == "user-read-email"


@pytest.mark.unit
def test_export_encrypted_row_returns_none_when_not_found(tmp_path):
    """export_encrypted_row returns None when the user has no stored tokens."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    assert export_encrypted_row(db_path, "ghost_user") is None


@pytest.mark.unit
def test_import_encrypted_row_raises_clear_error_on_missing_key(tmp_path):
    """import_encrypted_row raises SpotifyAuthError (not a bare KeyError) when a
    required key is missing from the row dict, e.g. a malformed/truncated row
    that crossed the D1 -> local scratch file network boundary."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    incomplete_row = {
        "refresh_token": "ciphertext_refresh",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "scopes": "user-read-email",
        # "access_token" missing
    }

    with pytest.raises(SpotifyAuthError, match="access_token"):
        import_encrypted_row(db_path, "user1", incomplete_row)
