"""PKCE (Proof Key for Code Exchange) utilities for Spotify OAuth.

RFC 7636: https://datatracker.ietf.org/doc/html/rfc7636
"""
import secrets
import hashlib
import base64


def generate_code_verifier(length: int = 96) -> str:
    """Generate a cryptographically random code_verifier.

    Per RFC 7636 §4.1:
    - Length: 43–128 characters
    - Character set: [A-Za-z0-9-._~] (URL-safe, no padding)

    Args:
        length: Number of random bytes to use as entropy. Default 96 gives a
                128-character verifier after base64url encoding (which is the max).

    Returns:
        A URL-safe base64-encoded string with no padding ('=').

    Raises:
        ValueError: If length is not in [32, 96] (ensures output is 43–128 chars).
    """
    if not 32 <= length <= 96:
        raise ValueError(f"length must be between 32 and 96, got {length}")
    raw = secrets.token_bytes(length)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_code_challenge(code_verifier: str) -> str:
    """Derive the S256 code_challenge from a code_verifier.

    Per RFC 7636 §4.2:
        code_challenge = BASE64URL(SHA256(ASCII(code_verifier)))

    Args:
        code_verifier: The verifier string from generate_code_verifier().

    Returns:
        A URL-safe base64-encoded SHA-256 digest with no padding.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
