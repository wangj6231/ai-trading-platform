import { NextResponse } from "next/server";
import { paperServerConfig } from "./server-runtime";
import { PaperHttpError, safePaperCode } from "./http-errors";
import { boundedText, safeCorrelation } from "./http-bounds";

const identifier = /^[A-Za-z0-9_-]{1,128}$/;
const journalQueries = new Set(["limit", "cursor", "as_of", "symbol", "side", "result", "closed_from", "closed_to", "tag"]);
const pageQueries = new Set(["limit", "cursor", "as_of"]);
const analyticsQueries = new Set(["symbol", "side", "result", "closed_from", "closed_to"]);
function fail(code: ConstructorParameters<typeof PaperHttpError>[0], status: number) {
  return NextResponse.json({ error: { code, message: new PaperHttpError(code, status).message } }, { status, headers: { "Cache-Control": "no-store" } });
}
export async function paperProxy(request: Request, segments: string[]) {
  const config = paperServerConfig();
  if (config.public.mode !== "HTTP" || !config.credential || !config.accountId || !config.origin) return fail("BOOTSTRAP_REQUIRED", 503);
  let headerBytes = 0, headerCount = 0;
  for (const [key, value] of request.headers) {
    headerCount++;
    if (headerCount > 64 || key.length > 128 || value.length > 4096) return fail("VALIDATION_ERROR", 422);
    headerBytes += new TextEncoder().encode(key + value).byteLength;
    if (headerBytes > 16384) return fail("VALIDATION_ERROR", 422);
  }
  if (headerCount > 64 || headerBytes > 16384 || request.url.length > 6144) return fail("VALIDATION_ERROR", 422);
  const target = new URL(request.url);
  if (new TextEncoder().encode(target.search).byteLength > 4096) return fail("VALIDATION_ERROR", 422);
  // Next may construct request.url with its internal localhost hostname.
  // Validate the incoming local authority; never forward it to the backend.
  const authority = request.headers.get("host") ?? target.host;
  if (authority !== new URL(config.origin).host || request.headers.get("origin") && request.headers.get("origin") !== config.origin ||
      ["cross-site", "same-site"].includes(request.headers.get("sec-fetch-site") ?? "") ||
      request.method !== "GET" && request.headers.get("origin") !== config.origin) return fail("FORBIDDEN", 403);
  if (segments[0] !== "accounts" || !segments[1] || !identifier.test(segments[1])) return fail("NOT_FOUND", 404);
  if (segments[1] !== config.accountId) return fail("FORBIDDEN", 403);
  const suffix = segments.slice(2);
  if (suffix.some(part => !identifier.test(part))) return fail("NOT_FOUND", 404);
  const path = suffix.join("/");
  const method = request.method;
  const allowed = method === "GET" && (path === "" || /^(orders|positions|trades|journal|analytics)$/.test(path) || /^(orders|trades|journal)\/[A-Za-z0-9_-]+$/.test(path) || /^trades\/[A-Za-z0-9_-]+\/(fills|attachments)$/.test(path)) ||
    method === "POST" && (path === "orders" || /^orders\/[A-Za-z0-9_-]+\/cancel$/.test(path)) || method === "PATCH" && /^journal\/[A-Za-z0-9_-]+\/metadata$/.test(path);
  if (!allowed) return fail("NOT_FOUND", 404);
  const allowedQuery = path === "trades" || path === "journal" ? journalQueries : path === "analytics" ? analyticsQueries : path === "orders" || /\/(fills|attachments)$/.test(path) ? pageQueries : new Set<string>();
  for (const key of target.searchParams.keys()) if (!allowedQuery.has(key) || target.searchParams.getAll(key).length !== 1) return fail("VALIDATION_ERROR", 422);
  const headers = new Headers({ Accept: "application/json", Authorization: `Bearer ${config.credential}` });
  for (const name of ["X-Request-ID", "X-Correlation-ID"]) { const value = safeCorrelation(request.headers.get(name)); if (value) headers.set(name, value); }
  let body: string | undefined;
  if (method === "PATCH" || method === "POST" && path === "orders") {
    const length = request.headers.get("Content-Length");
    if (length !== null && (!/^[0-9]{1,10}$/.test(length) || Number(length) > 32768)) return fail("VALIDATION_ERROR", 422);
    try { body = await boundedText(request.body, 32768); if (length !== null && new TextEncoder().encode(body).byteLength !== Number(length)) return fail("VALIDATION_ERROR", 422); JSON.parse(body); } catch { return fail("VALIDATION_ERROR", 422); }
    headers.set("Content-Type", "application/json");
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.signal.addEventListener("abort", abort, { once: true }); if (request.signal.aborted) abort();
  let timeout = false;
  const timer = setTimeout(() => { timeout = true; controller.abort(); }, 10_000);
  try {
    const backend = new URL(process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000");
    const prefix = process.env.PAPER_BACKEND_API_PREFIX ?? "/api/v1";
    if (!/^\/(?:[A-Za-z0-9_-]+\/?)*$/.test(prefix) || !["http:", "https:"].includes(backend.protocol)) return fail("BOOTSTRAP_REQUIRED", 503);
    const url = new URL(`${prefix.replace(/\/$/, "")}/paper/accounts/${encodeURIComponent(config.accountId)}${path ? `/${path}` : ""}${target.search}`, backend);
    const response = await fetch(url, { method, body, headers, cache: "no-store", redirect: "error", signal: controller.signal });
    let text: string;
    try { text = await boundedText(response.body, 2 * 1024 * 1024); } catch { return fail("INVALID_RESPONSE", 502); }
    let data: unknown; try { data = JSON.parse(text); } catch { return fail("INVALID_RESPONSE", 502); }
    const forwarded = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store" });
    for (const name of ["ETag", "X-Request-ID", "X-Correlation-ID"]) { const raw = response.headers.get(name); const value = name === "ETag" ? raw && raw.length <= 256 ? raw : null : safeCorrelation(raw); if (value) forwarded.set(name, value); }
    if (!response.ok) {
      const code = safePaperCode((data as { error?: { code?: unknown } })?.error?.code, response.status);
      return NextResponse.json({ error: { code, message: new PaperHttpError(code).message } }, { status: response.status, headers: forwarded });
    }
    return NextResponse.json(data, { status: response.status, headers: forwarded });
  } catch { return fail(timeout ? "BACKEND_TIMEOUT" : "BACKEND_UNAVAILABLE", timeout ? 504 : 503); }
  finally { clearTimeout(timer); request.signal.removeEventListener("abort", abort); }
}
