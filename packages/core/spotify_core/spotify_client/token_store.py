"""Fernet-encrypted token persistence for Spotify OAuth tokens.

Tokens are encrypted before writing to SQLite and decrypted only here,
inside the spotify_client module boundary.
"""
import logging
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union

from cryptography.fernet import Fernet

from spotify_core.db.migrations import get_connection

logger = logging.getLogger(__name__)


def _parse_expires_at(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def save_tokens(
    db_path: Union[str, Path],
    user_id: str,
    token_dict: dict,
    fernet_key: bytes,
) -> None:
    """Encrypt and persist OAuth tokens for a user.

    Encrypts ``access_token`` and ``refresh_token`` with Fernet before
    writing.  Uses ``INSERT OR REPLACE`` so an existing row is atomically
    overwritten.

    Args:
        db_path: Path to the SQLite database (must already be initialised).
        user_id: Spotify user ID (primary key).
        token_dict: Dict with keys ``access_token``, ``refresh_token``,
            ``expires_in`` (int, seconds from now), and ``scope`` (str).
        fernet_key: Raw Fernet key bytes used for encryption.
    """
    f = Fernet(fernet_key)

    encrypted_access = f.encrypt(token_dict["access_token"].encode()).decode()
    encrypted_refresh = f.encrypt(token_dict["refresh_token"].encode()).decode()

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_dict["expires_in"]))
    expires_at_str = expires_at.isoformat()

    scopes = token_dict.get("scope", "")

    with closing(get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO spotify_tokens
                (user_id, access_token, refresh_token, expires_at, scopes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, encrypted_access, encrypted_refresh, expires_at_str, scopes),
        )
        conn.commit()

    logger.info("Tokens saved for user %s", user_id)


def load_tokens(
    db_path: Union[str, Path],
    user_id: str,
    fernet_key: bytes,
) -> dict | None:
    """Load and decrypt OAuth tokens for a user.

    Args:
        db_path: Path to the SQLite database.
        user_id: Spotify user ID to look up.
        fernet_key: Raw Fernet key bytes used for decryption.

    Returns:
        Dict with keys ``access_token``, ``refresh_token``, ``expires_at``
        (``datetime``), and ``scopes`` (``str``), or ``None`` if not found.
    """
    with closing(get_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at, scopes "
            "FROM spotify_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        logger.debug("No token row found for user %s", user_id)
        return None

    f = Fernet(fernet_key)
    access_token = f.decrypt(row["access_token"].encode()).decode()
    refresh_token = f.decrypt(row["refresh_token"].encode()).decode()

    expires_at = _parse_expires_at(row["expires_at"])

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "scopes": row["scopes"] or "",
    }


def is_token_expired(
    db_path: Union[str, Path],
    user_id: str,
) -> bool:
    """Check whether the stored token for a user is expired or missing.

    Does **not** require a Fernet key — expiry is determined from the
    plaintext ``expires_at`` timestamp column.

    Args:
        db_path: Path to the SQLite database.
        user_id: Spotify user ID to check.

    Returns:
        ``True`` if the token is expired or the row does not exist,
        ``False`` if the token is still valid.
    """
    with closing(get_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT expires_at FROM spotify_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        logger.debug("is_token_expired: no row for user %s — treating as expired", user_id)
        return True

    expires_at = _parse_expires_at(row["expires_at"])

    # Compare in a timezone-aware manner.
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        # Stored as naive UTC — attach UTC tzinfo for comparison.
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    expired = expires_at < now
    logger.debug(
        "is_token_expired: user=%s expires_at=%s now=%s expired=%s",
        user_id,
        expires_at,
        now,
        expired,
    )
    return expired


def delete_tokens(
    db_path: Union[str, Path],
    user_id: str,
) -> None:
    """Delete the token row for a user.

    No-op if the user has no stored tokens.

    Args:
        db_path: Path to the SQLite database.
        user_id: Spotify user ID whose tokens should be removed.
    """
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            "DELETE FROM spotify_tokens WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()

    logger.info("Tokens deleted for user %s", user_id)
