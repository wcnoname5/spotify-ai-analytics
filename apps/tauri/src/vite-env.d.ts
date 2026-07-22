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

// Shared .sql files imported as raw text via the `@sql` alias, e.g.
// `import sql from "@sql/top_artists.sql?raw"`.
declare module "*.sql?raw" {
  const content: string;
  export default content;
}
