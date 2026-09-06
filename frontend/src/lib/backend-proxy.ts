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

export async function proxyBackend(path: string, init?: RequestInit): Promise<NextResponse> {
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
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
      signal: controller.signal,
    });
    const text = await response.text();
    const contentType = response.headers.get("content-type");
    return new NextResponse(text || null, {
      status: response.status,
      headers: contentType ? { "Content-Type": contentType } : undefined,
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
  });
}
