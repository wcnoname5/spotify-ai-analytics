"""Typed exceptions for the Spotify client layer.

These let upstream layers (MCP server, agent) react to specific failure modes
without parsing exception message strings.
"""


class SpotifyError(Exception):
    """Base class for all Spotify client errors."""


class SpotifyAuthError(SpotifyError):
    """Tokens are missing, invalid, or cannot be refreshed.

    Raised when no token is stored for the user, when stored tokens cannot be
    refreshed, or when the API returns 401 even after a refresh retry.
    """


class SpotifyPremiumRequiredError(SpotifyError):
    """Endpoint requires a Spotify Premium account but the connected account is not Premium."""


class SpotifyNoActiveDeviceError(SpotifyError):
    """Playback command failed because no active Spotify device was found."""
