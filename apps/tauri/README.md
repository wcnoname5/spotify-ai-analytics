# Spotify Dashboard (Tauri app)

A Tauri 2 + Vue 3 desktop dashboard for personal Spotify listening history. It reads a
local SQLite cache (`data/history.db` by default) via `tauri-plugin-sql`, using the same
`.sql` queries as the rest of the project (`packages/core/spotify_core/db/sql/`). On
startup it does a quick incremental sync from the Cloudflare Worker/D1 into that local
cache, then renders everything from SQLite.

## Running

```bash
npm run tauri dev   # real data: opens the desktop shell, uses the local db + startup sync
npm run dev          # sample data only: plain browser preview, no Tauri APIs available
```

`npm run dev` runs the frontend in a normal browser tab. Since the Tauri APIs
(`tauri-plugin-sql`, etc.) don't exist outside the desktop shell, this mode always shows
bundled sample data — it's meant for fast UI iteration, not for looking at your own
history. Use `npm run tauri dev` to see real data.

## Environment variables

Config is read from the **repo-root** `.env` (one level above `apps/tauri`), not from
`apps/tauri/.env`. See `.env.example` at the repo root.

- `HISTORY_DB_PATH` — optional path to the local SQLite cache. Defaults to
  `data/history.db` (relative to the repo root) if unset.
- `WORKER_URL` — the Cloudflare Worker base URL used for the startup sync
  (`https://<name>.workers.dev`).
- `WORKER_AUTH_TOKEN` — Bearer token for the Worker. If either `WORKER_URL` or this is
  unset, the app skips syncing and shows a non-blocking "not configured" notice, then
  falls back to whatever is already cached locally.

**Dev-bundle token caveat:** in `npm run tauri dev`, `WORKER_AUTH_TOKEN` is inlined into
the built JS bundle via Vite's `define` (see `vite.config.ts`) — fine for local
development, but this is not how a shipped build should hold a secret. Moving the token
into the OS keychain (e.g. via a Tauri secure-storage plugin) is deferred until the app
is actually packaged for distribution.
