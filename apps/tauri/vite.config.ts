import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// Dev-only: read WORKER_URL / WORKER_AUTH_TOKEN from the repo root .env and
// proxy /api -> Worker, adding the Bearer header server-side. The token never
// reaches the client bundle; the browser just fetches a relative /api/... .
// (Production/Tauri will use the OS keychain instead — see project spec.)
function repoEnv(): Record<string, string> {
  try {
    // @ts-expect-error __dirname exists in the vite config's node context
    const text = readFileSync(resolve(__dirname, "../../.env"), "utf-8");
    return Object.fromEntries(
      text
        .split("\n")
        .map((l) => l.match(/^([A-Z_]+)=(.*)$/))
        .filter((m): m is RegExpMatchArray => m !== null)
        .map((m) => [m[1], m[2].trim()])
    );
  } catch {
    return {};
  }
}
const env = repoEnv();

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [vue()],

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
    proxy: env.WORKER_URL
      ? {
          "/api": {
            target: env.WORKER_URL,
            changeOrigin: true,
            headers: { Authorization: `Bearer ${env.WORKER_AUTH_TOKEN ?? ""}` },
          },
        }
      : undefined,
  },
}));
