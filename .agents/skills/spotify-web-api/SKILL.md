---
name: spotify-web-api
description: Use when writing, reviewing, or debugging any code that calls the Spotify Web API — including auth flows, endpoint selection, token handling, rate limiting, scopes, and redirect URIs. Also use when choosing between authorization flows or handling 429/error responses.
---

# Spotify Web API

## Overview

Reference for building against the Spotify Web API correctly. Covers authorization, endpoints, tokens, rate limits, error handling, and ToS compliance.

**Spec:** Always consult the [Spotify OpenAPI schema](https://developer.spotify.com/reference/web-api/open-api-schema.yaml) for endpoint paths, parameters, and response shapes. Never guess field names or routes.

---

## Authorization Flows

| Scenario | Flow |
|---|---|
| User-specific data (frontend-only) | **Authorization Code with PKCE** |
| User-specific data (secure backend) | Authorization Code (non-PKCE acceptable) |
| Public, non-user data | Client Credentials |
| **Never use** | ~~Implicit Grant~~ (deprecated Nov 2025) |

- PKCE tutorial: https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- Code flow tutorial: https://developer.spotify.com/documentation/web-api/tutorials/code-flow

---

## Redirect URIs

- **Local dev:** `http://127.0.0.1:{port}/callback` only
- **Production:** must use HTTPS
- **Never use:** `http://localhost`, wildcard URIs
- Reference: https://developer.spotify.com/documentation/web-api/concepts/redirect_uri

This project enforces `127.0.0.1` in `packages/core/spotify_client/` — do not add `localhost` variants.

---

## Scopes

Request **only the minimum scopes** needed for the features being built. Do not request broad scopes preemptively.

Reference: https://developer.spotify.com/documentation/web-api/concepts/scopes

---

## Token Management

- Never expose `Client Secret` in client-side code
- Store tokens encrypted (this project uses Fernet via `TOKEN_ENCRYPT_KEY`)
- Implement token refresh before access tokens expire
- Decrypt tokens only inside `packages/core/spotify_client/`
- Refresh tutorial: https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens

---

## Rate Limits

On HTTP **429**:
1. Read the `Retry-After` header for the required wait time
2. Use **exponential backoff** — do not retry immediately or in tight loops
3. Surface the delay to callers, don't silently swallow it

---

## Deprecated Endpoints — Do Not Use

| Deprecated | Use instead |
|---|---|
| `/playlists/{id}/tracks` | `/playlists/{id}/items` |
| Type-specific library endpoints | `/me/library` |

---

## Error Handling

- Handle **all** HTTP error codes documented in the OpenAPI schema
- Read the returned error body and surface the message meaningfully to the user
- Common codes: 400 (bad request), 401 (expired/invalid token), 403 (forbidden scope), 404 (not found), 429 (rate limited), 5xx (Spotify server error)

---

## Developer Terms of Service

- Do not cache Spotify content beyond what is needed for immediate use
- Always attribute content to Spotify in any UI
- Do not use the API to train ML models on Spotify data
- Full terms: https://developer.spotify.com/terms

---

## Quick Reference

```python
# Auth header format
headers = {"Authorization": f"Bearer {access_token}"}

# 429 handling
if response.status_code == 429:
    retry_after = int(response.headers.get("Retry-After", 1))
    time.sleep(retry_after)  # then retry with backoff

# Preferred playlist items endpoint
GET /playlists/{playlist_id}/items
```
