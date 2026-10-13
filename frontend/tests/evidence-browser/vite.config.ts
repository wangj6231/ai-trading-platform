import path from "node:path";
import { defineConfig } from "vite";
import { createReadStream } from "node:fs";
const frontend = path.resolve(__dirname, "../..");
export default defineConfig({ root: __dirname, cacheDir: path.join(frontend, "node_modules/.cache/evidence-v2-vite"), esbuild: { jsx: "automatic" }, css: { postcss: frontend }, resolve: { alias: { "@": path.join(frontend, "src") } },
  plugins: [{ name: "local-recorded-evidence-only", configureServer(server) { server.middlewares.use((request, response, next) => {
    const file = request.url === "/recorded-analysis.json" ? "experiments/backend_evaluation_performance_v1/final25_btc_analysis_response.json" : request.url === "/recorded-candles.json" ? "docs/frontend-chart-evidence-v2/recorded-candles.json" : request.url === "/recorded-candles-1h.json" ? "docs/frontend-chart-evidence-v2/recorded-candles-1h.json" : null;
    if (!file) return next();
    response.setHeader("Content-Type", "application/json"); response.setHeader("Cache-Control", "no-store");
    createReadStream(path.resolve(frontend, "..", file)).on("error", () => { response.statusCode = 404; response.end(); }).pipe(response);
  }); } }], server: { host: "127.0.0.1", port: 4179, strictPort: true } });
