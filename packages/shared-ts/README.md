# shared-ts

TypeScript imported by **both** the Cloudflare Worker (`worker/`) and the desktop
frontend (`apps/tauri/`). Same purpose as `spotify_core/db/sql/`: things that
must not exist twice.

| module | why it is shared |
|---|---|
| `fernet.ts` | The Worker cron decrypts tokens the desktop app encrypted. A second implementation that disagreed by one byte would produce tokens one side cannot read — and the failure would surface hours later, in a cron run. |
| `pkce.ts` | Only the desktop app needs it today. It lives here because it is the other half of the same OAuth flow, and splitting the flow across two conventions is how the halves drift. |

## How each side imports it

- **Worker**: relative import (`../../packages/shared-ts/fernet`). Wrangler's
  bundler follows it; there is no build step to configure.
- **Frontend**: the `@shared` alias in `apps/tauri/vite.config.ts`, mirrored in
  `tsconfig.json` `paths` so `vue-tsc` agrees with Vite.

## Constraints

Web-standard APIs only — `crypto.subtle`, `fetch`, `TextEncoder`. No Node
built-ins and no npm dependencies: this code runs in a Cloudflare Worker and in
a WebView, and neither has a Node runtime.
