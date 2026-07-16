import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => {
  // Repo root .env (one level above apps/tauri) — HISTORY_DB_PATH / WORKER_URL /
  // WORKER_AUTH_TOKEN. loadEnv reads it without an `VITE_` prefix requirement.
  const env = loadEnv(mode, resolve(__dirname, "../.."), "");

  return {
    plugins: [vue()],

    resolve: {
      alias: {
        "@sql": resolve(__dirname, "../../packages/core/spotify_core/db/sql"),
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

    define: {
      __HISTORY_DB_PATH__: JSON.stringify(
        (env.HISTORY_DB_PATH || resolve(__dirname, "../../data/history.db")).replace(/\\/g, "/")
      ),
      __WORKER_URL__: JSON.stringify(env.WORKER_URL ?? ""),
      // dev-only; keychain before packaging
      __WORKER_AUTH_TOKEN__: JSON.stringify(env.WORKER_AUTH_TOKEN ?? ""),
    },
  };
});
