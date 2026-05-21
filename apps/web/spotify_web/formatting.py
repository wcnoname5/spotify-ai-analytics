"""Pure formatting helpers for the dashboard UI."""
from typing import Optional


def spotify_uri_to_url(uri: Optional[str]) -> Optional[str]:
    """Convert a 'spotify:track:<id>' URI to an open.spotify.com track URL.

    Returns None for empty values or any URI that is not a non-empty track URI
    (e.g. podcast-episode URIs).
    """
    if not uri or not uri.startswith("spotify:track:"):
        return None
    track_id = uri.split(":", 2)[2]
    if not track_id:
        return None
    return f"https://open.spotify.com/track/{track_id}"


def format_duration_ms(ms: Optional[int]) -> str:
    """Format a millisecond duration as a human string, e.g. '3h 12m' or '45m'."""
    if not ms or ms < 0:
        return "0m"
    total_minutes = ms // 60_000
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
