/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

// plotly.js-basic-dist-min ships no types; reuse the full plotly.js ones.
declare module "plotly.js-basic-dist-min" {
  import Plotly from "plotly.js";
  export default Plotly;
  export * from "plotly.js";
}

// Injected by vite.config.ts `define` — see there for values.
declare const __HISTORY_DB_PATH__: string;
declare const __WORKER_URL__: string;
declare const __WORKER_AUTH_TOKEN__: string;

// Shared .sql files imported as raw text via the `@sql` alias, e.g.
// `import sql from "@sql/top_artists.sql?raw"`.
declare module "*.sql?raw" {
  const content: string;
  export default content;
}
