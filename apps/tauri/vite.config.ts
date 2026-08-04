import { resolve } from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// Config is no longer baked in at build time — the app reads it at runtime via
// `spotify-mcp config get` (see src/lib/config.ts). That kept the auth token out
// of the bundle and lets the Setup page change settings without a rebuild.
// https://vite.dev/config/
export default defineConfig(async () => {
  return {
    plugins: [vue()],

    resolve: {
      alias: {
        "@sql": resolve(__dirname, "../../packages/core/spotify_core/db/sql"),
        // TS shared with the Worker (Fernet, PKCE). Mirrored in tsconfig.json
        // `paths` so vue-tsc resolves it the same way Vite does.
        "@shared": resolve(__dirname, "../../packages/shared-ts"),
      },
    },

    // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
    //
    // 1. prevent Vite from obscuring rust errors
    clearScreen: false,
    // 2. tauri expects a fixed port, fail if that port is not available
    server: {
      port: 1420,
      strictPort: true,
      host: host || false,
      hmr: host
        ? {
            protocol: "ws",
            host,
            port: 1421,
          }
        : undefined,
      watch: {
        // 3. tell Vite to ignore watching `src-tauri`
        ignored: ["**/src-tauri/**"],
      },
      fs: {
        // allow serving the shared sql/ dir from outside apps/tauri (@sql alias)
        allow: [resolve(__dirname, "../..")],
      },
    },

  };
});
