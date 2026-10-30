import { NextResponse } from "next/server";

const backendUrl = process.env.BACKEND_API_URL ?? "http://localhost:8000";
const DEFAULT_BACKEND_PROXY_TIMEOUT_MS = 10_000;
const MAX_BACKEND_PROXY_TIMEOUT_MS = 120_000;

function backendProxyTimeoutMs(): number {
  const configured = Number(process.env.BACKEND_PROXY_TIMEOUT_MS);
  if (
    Number.isInteger(configured) &&
    configured > 0 &&
    configured <= MAX_BACKEND_PROXY_TIMEOUT_MS
  ) {
    return configured;
  }
  return DEFAULT_BACKEND_PROXY_TIMEOUT_MS;
}

function proxyError(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status });
}

const requestHeaderNames = ["Authorization", "Idempotency-Key", "If-Match", "X-Request-ID", "X-Correlation-ID"];
const responseHeaderNames = ["Content-Type", "Cache-Control", "ETag", "X-Request-ID", "X-Correlation-ID"];

export function forwardBackendHeaders(incoming?: Headers, supplied?: HeadersInit): Headers {
  const headers = new Headers(supplied);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  for (const name of requestHeaderNames) {
    const value = incoming?.get(name);
    if (value !== null && value !== undefined) headers.set(name, value);
  }
  return headers;
}

export async function proxyBackend(path: string, init?: RequestInit, incoming?: Headers): Promise<NextResponse> {
  const controller = new AbortController();
  const callerSignal = init?.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  let timedOut = false;
  if (callerSignal?.aborted) {
    abortFromCaller();
  } else {
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }
  const timeout = setTimeout(() => {
    if (controller.signal.aborted) return;
    timedOut = true;
    controller.abort();
  }, backendProxyTimeoutMs());

  try {
    const response = await fetch(`${backendUrl}${path}`, {
      ...init,
      cache: "no-store",
      headers: forwardBackendHeaders(incoming, init?.headers),
      signal: controller.signal,
    });
    const text = await response.text();
    const headers = new Headers();
    for (const name of responseHeaderNames) {
      const value = response.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    return new NextResponse(text || null, {
      status: response.status,
      headers,
    });
  } catch {
    if (timedOut) {
      return proxyError(504, "BACKEND_TIMEOUT", "Backend request timed out.");
    }
    return proxyError(503, "BACKEND_UNAVAILABLE", "Backend service is unavailable.");
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export async function proxyJsonPost(request: Request, path: string): Promise<NextResponse> {
  let body: string;
  try {
    body = await request.text();
    if (!body.trim()) throw new SyntaxError("empty request body");
    JSON.parse(body);
  } catch {
    return proxyError(
      400,
      "MALFORMED_REQUEST_BODY",
      "The request body must contain valid JSON.",
    );
  }
  return proxyBackend(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: request.signal,
  }, request.headers);
}
