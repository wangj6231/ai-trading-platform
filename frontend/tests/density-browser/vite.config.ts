import path from "node:path";
import { createReadStream, readFileSync } from "node:fs";
import { defineConfig } from "vite";
const frontend = path.resolve(__dirname, "../..");
const baseline = process.env.EVIDENCE_BASELINE === "1";
const archive = path.resolve(frontend, "../docs/frontend-chart-evidence-v3/baseline");
export default defineConfig({ root: __dirname, cacheDir: path.join(frontend, "node_modules/.cache/density-vite"), esbuild: { jsx: "automatic" }, css: { postcss: frontend }, resolve: { dedupe: ["react", "react-dom", "zod", "lightweight-charts"], alias: { "tailwindcss": path.join(frontend, "node_modules/tailwindcss/index.css"), "@": path.join(baseline ? archive : frontend, "src") } }, plugins: [
  { name: "measure-real-chart", enforce: "pre", transform(code, id) { if (id.endsWith("/components/price-chart.tsx")) {
    code = code.replaceAll("\r\n", "\n");
    const instrument = path.join(__dirname, "instrument.js").replaceAll("\\", "/");
    return `import { measureRender } from "${instrument}";\n` + code.replace('from "lightweight-charts"', `from "${instrument}"`).replace('const renderZones = () => {', 'const renderZones = measureRender(() => {').replace('    };\n    renderRef.current = renderZones;', '    });\n    renderRef.current = renderZones;');
  } if (id.endsWith("fixture.tsx")) return code.replace('return <main', `window.evidenceModel = { source, candles: chartCandles, signal: chartSignal${baseline ? "" : ", density"} }; return <main`); } },
  { name: "recorded-stream", configureServer(server) { server.middlewares.use((request, response, next) => {
    if (request.url === "/fixture.tsx" && baseline) { response.setHeader("Content-Type", "application/javascript"); return next(); }
    const file = request.url === "/recorded-analysis.json" ? "experiments/backend_evaluation_performance_v1/final25_btc_analysis_response.json" : request.url === "/recorded-candles.json" ? "docs/frontend-chart-evidence-v2/recorded-candles.json" : request.url === "/recorded-candles-1h.json" ? "docs/frontend-chart-evidence-v2/recorded-candles-1h.json" : null;
    if (!file) return next(); response.setHeader("Content-Type", "application/json"); createReadStream(path.resolve(frontend, "..", file)).pipe(response);
  }); } },
  { name: "baseline-fixture", load(id) { if (baseline && id === path.join(__dirname, "fixture.tsx").replaceAll("\\", "/")) return readFileSync(path.join(archive, "evidence-fixture.tsx"), "utf8"); } },
], server: { host: "127.0.0.1", port: 4180, strictPort: true, fs: { allow: [frontend, archive] } } });
