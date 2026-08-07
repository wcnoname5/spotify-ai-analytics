# Spotify AI Analytics

A desktop app for your own Spotify listening history: long-term charts, and AI-written
listening reports.

Spotify's API only hands back your ~50 most recent plays, so anything that runs purely
on your machine loses history whenever you don't open it for a few days. This app
solves that by keeping your history in **your own Cloudflare account**: a tiny worker
collects your plays every hour, whether or not the app is running.

**Your data stays yours.** There is no server operated by anyone else. You paste a
Cloudflare API token once, the app deploys the backend into your account, and the token
is never stored. Everything fits inside Cloudflare's free tier.

> **Status:** pre-release, Windows only. macOS is not supported yet.

---

## Install

1. Download `spotify-analytics_<version>_x64-setup.exe` from
   [Releases](https://github.com/wcnoname5/spotify-ai-analytics/releases/latest) and run it.
2. Launch the app. A **Setup** window opens and walks you through four steps.

You do not need Python, Node, or any developer tooling installed.

### What you'll need before you start

**A Spotify app**: create one at the [Spotify developer dashboard](https://developer.spotify.com/dashboard). You only need its Client ID.

> The redirect URI must be **exactly** `http://127.0.0.1:8888/callback`.
> Not `localhost` — Spotify stopped accepting it in November 2025.

**A Cloudflare API token**: create one at [dash.cloudflare.com](https://dash.cloudflare.com/profile/api-tokens) → *Create Custom Token*, with these two permissions:

- `[Account] [D1] [Edit]`
- `[Account] [Workers Scripts] [Edit]`

The app uses it once to deploy, then discards it. It is never written to disk.

**(Highly Recommendded) Your Spotify data export:** Spotify will email you your full listening
history if you request it under *Privacy Settings → Download your data* (it takes a few days).
Import it and your charts go back years instead of starting from today.

### Setup, step by step

| Step | What happens |
|---|---|
| **Spotify Client ID** | Just paste it |
| **Cloud sync** | Paste the Cloudflare token, pick a name, press Deploy. Takes a few minutes and creates a database and a worker in your account |
| **Authorize Spotify** | Opens your browser. Your tokens are encrypted before they leave the machine and are stored only in your own database |
| **Listening history** | Import your export folder, or just grab the last 50 plays and start from now |

The steps are ordered on purpose — authorizing is blocked until the cloud step is done,
because your database is the only place tokens are allowed to live.

---

## What you get

- **A dashboard** — top artists and tracks, listening trends by day/week/month,
  activity patterns by hour, and totals for any date range.
- **Hourly sync that runs without you.** Your worker collects plays on a schedule, so
  closing the app for a week costs you nothing.
- **AI listening reports** *(optional)* — a weekly, monthly, or quarterly writeup of
  what you've been listening to, generated with Gemini or OpenAI. Add an API key in
  Setup to enable it. Reports are saved and can be re-read or exported as Markdown.

The app updates itself when a new release is published.

---

## Development

Requires [uv](https://docs.astral.sh/uv/), Node, and Rust.

```bash
uv sync                                # Python dependencies
cd apps/tauri && npm install

$env:SPOTIFY_CONFIG="./dev.config.json"  # keeps dev data out of your real install
npm run tauri dev
```

| | |
|---|---|
| `apps/tauri/` | The desktop app — Vue + TypeScript frontend, Rust shell |
| `worker/` | The Cloudflare Worker (TypeScript) |
| `packages/shared-ts/` | Code imported by both the worker and the frontend |
| `packages/core/` | Python: report generation, plus the shared SQL both languages use |
| `apps/mcp/` | An optional MCP server for Claude Desktop — not part of the app |

```bash
cd apps/tauri && npm test              # frontend + shared TS
cd apps/tauri/src-tauri && cargo test  # Rust
cd worker && npm run typecheck
uv run pytest                          # Python
```

**Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before changing anything** — it
covers the system boundaries and, more importantly, the invariants that previous bugs
were made of. [`CLAUDE.md`](CLAUDE.md) has the working conventions.

---

## License

[MIT](LICENSE)
