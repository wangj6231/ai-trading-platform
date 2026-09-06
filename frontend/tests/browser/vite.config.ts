import path from "node:path";
import { defineConfig } from "vite";

const frontend = path.resolve(__dirname, "../..");

export default defineConfig({
  root: __dirname,
  cacheDir: path.join(frontend, "node_modules/.cache/zone-browser-vite"),
  esbuild: { jsx: "automatic" },
  css: { postcss: frontend },
  resolve: {
    alias: {
      "@": path.join(frontend, "src"),
      // Only the projection adapter is controlled. The component, ViewModel,
      // lifecycle timestamps, browser layout and production CSS are real.
      "lightweight-charts": path.join(__dirname, "projection-adapter.ts"),
    },
  },
  server: { host: "127.0.0.1", port: 4178, strictPort: true },
});
