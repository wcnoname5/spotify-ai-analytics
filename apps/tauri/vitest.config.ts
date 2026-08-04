import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

// Separate from vite.config.ts: that one loads the Vue plugin and the Tauri dev
// server settings, none of which a unit test needs. The alias is repeated
// because the tests import through it.
export default defineConfig({
  resolve: {
    alias: {
      "@shared": resolve(__dirname, "../../packages/shared-ts"),
      "@sql": resolve(__dirname, "../../packages/core/spotify_core/db/sql"),
    },
  },
  test: {
    // shared-ts is outside this package, so it has to be named explicitly.
    include: ["src/**/*.test.ts", "../../packages/shared-ts/**/*.test.ts"],
    // Node 20+ exposes crypto.subtle globally, which is all shared-ts uses —
    // no jsdom, no browser runner.
    environment: "node",
  },
});
