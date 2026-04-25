"""Tests for PKCE utility functions."""
import base64
import hashlib
import pytest
from spotify_core.spotify_client.pkce import generate_code_verifier, generate_code_challenge


@pytest.mark.unit
def test_verifier_default_length():
    """Default verifier is between 43 and 128 characters."""
    v = generate_code_verifier()
    assert 43 <= len(v) <= 128


@pytest.mark.unit
def test_verifier_is_url_safe_no_padding():
    """Verifier contains only URL-safe base64 characters and no '=' padding."""
    v = generate_code_verifier()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert all(c in allowed for c in v), f"Non-URL-safe char in: {v}"
    assert "=" not in v


@pytest.mark.unit
def test_verifier_different_each_call():
    """Two calls produce different verifiers."""
    assert generate_code_verifier() != generate_code_verifier()


@pytest.mark.unit
def test_verifier_invalid_length():
    """Length outside [32, 96] raises ValueError."""
    with pytest.raises(ValueError):
        generate_code_verifier(length=10)
    with pytest.raises(ValueError):
        generate_code_verifier(length=200)


@pytest.mark.unit
def test_challenge_known_vector():
    """S256 challenge matches manually computed value for a known verifier."""
    # Known vector: verifier = "abc", challenge = BASE64URL(SHA256("abc"))
    verifier = "abc"
    expected_digest = hashlib.sha256(b"abc").digest()
    expected = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
    assert generate_code_challenge(verifier) == expected


@pytest.mark.unit
def test_challenge_no_padding():
    """Challenge output contains no '=' padding."""
    v = generate_code_verifier()
    c = generate_code_challenge(v)
    assert "=" not in c


@pytest.mark.unit
def test_challenge_is_43_chars():
    """SHA-256 produces 32 bytes → base64url without padding is always 43 chars."""
    v = generate_code_verifier()
    c = generate_code_challenge(v)
    assert len(c) == 43


@pytest.mark.unit
def test_challenge_deterministic():
    """Same verifier always produces same challenge."""
    v = generate_code_verifier()
    assert generate_code_challenge(v) == generate_code_challenge(v)
