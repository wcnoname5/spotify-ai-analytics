"""Thin HTTP client for the Cloudflare Worker fronting D1.

D1 is the single source of truth for listening history and encrypted Spotify
tokens; this module is the *only* way the cron and local-sync scripts talk to
it. No direct D1 access, no retries, no pagination — just Bearer-authenticated
JSON requests matching the Worker's API contract exactly.
"""
from typing import Optional

import httpx


class WorkerClient:
    """Authenticated client for the Cloudflare Worker's D1-backed API.

    Args:
        base_url: Worker base URL (e.g. ``https://worker.example.workers.dev``).
        auth_token: Bearer token sent as ``Authorization`` on every request.
        http_client: Optional ``httpx.Client`` for dependency injection in
            tests. If ``None``, a new client is created on first use.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self._http_client = http_client
        self._owns_client = http_client is None

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client()
        return self._http_client

    def close(self) -> None:
        """Close the underlying HTTP client if it was created internally."""
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth_token}"}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self._client.request(
            method, self.base_url + path, headers=self._headers(), **kwargs
        )
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def get_cursor(self) -> int:
        """Return the last-synced played_at cursor in epoch ms (0 if unset)."""
        body = self._request("GET", "/api/cursor").json()
        return body["last_played_at_ms"]

    def post_cursor(self, ms: int) -> None:
        """Persist the last-synced played_at cursor in epoch ms."""
        self._request("POST", "/api/cursor", json={"last_played_at_ms": ms})

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def get_tokens(self, user_id: str) -> Optional[dict]:
        """Return the encrypted token row for user_id, or None if not found."""
        response = self._client.request(
            "GET",
            self.base_url + "/api/tokens",
            headers=self._headers(),
            params={"user_id": user_id},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def post_tokens(self, user_id: str, row: dict) -> None:
        """Upsert the encrypted token row for user_id."""
        self._request(
            "POST", "/api/tokens", params={"user_id": user_id}, json=row
        )

    # ------------------------------------------------------------------
    # Tracks
    # ------------------------------------------------------------------

    def get_tracks_since(self, since_ms: int) -> list[dict]:
        """Return listening_history rows played at or after since_ms."""
        body = self._request(
            "GET", "/api/tracks", params={"since": since_ms}
        ).json()
        return body["tracks"]

    def post_tracks(self, rows: list[dict]) -> int:
        """Insert listening_history rows; return the number inserted."""
        body = self._request(
            "POST", "/api/tracks", json={"tracks": rows}
        ).json()
        return body["inserted"]

    def get_tracks_count(self) -> int:
        """Return the total row count in listening_history."""
        body = self._request("GET", "/api/tracks/count").json()
        return body["count"]
