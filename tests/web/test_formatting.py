"""Tests for spotify_web.formatting."""
from spotify_web.formatting import spotify_uri_to_url, format_duration_mins


def test_uri_to_url_valid():
    assert spotify_uri_to_url("spotify:track:abc123") == \
        "https://open.spotify.com/track/abc123"


def test_uri_to_url_none():
    assert spotify_uri_to_url(None) is None


def test_uri_to_url_empty_string():
    assert spotify_uri_to_url("") is None


def test_uri_to_url_non_track():
    assert spotify_uri_to_url("spotify:episode:xyz789") is None


def test_uri_to_url_empty_track_id():
    assert spotify_uri_to_url("spotify:track:") is None


def test_format_duration_zero():
    assert format_duration_mins(0) == "0m"


def test_format_duration_none():
    assert format_duration_mins(None) == "0m"


def test_format_duration_minutes_only():
    assert format_duration_mins(45) == "45m"


def test_format_duration_hours_and_minutes():
    assert format_duration_mins(3 * 60 + 12) == "3h 12m"
