/** Byte-bounded stream read; no request/response payload enters diagnostics. */
export async function boundedText(body: ReadableStream<Uint8Array> | null, maximum: number, timeoutMs = 10000): Promise<string> {
  if (!body) return "";
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const deadline = Date.now() + timeoutMs;
  try {
    while (true) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const value = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("bounded stream deadline")), Math.max(1, deadline - Date.now())); }),
      ]).finally(() => { if (timer) clearTimeout(timer); });
      if (value.done) break;
      size += value.value.byteLength;
      if (size > maximum) throw new Error("bounded stream overflow");
      // Empty chunks must not grow the retained container without using bytes.
      if (value.value.byteLength > 0) chunks.push(value.value);
    }
    const joined = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.byteLength; }
    return new TextDecoder("utf-8", { fatal: true }).decode(joined);
  } finally { void reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

export function safeCorrelation(value: string | null): string | null {
  return value && /^[A-Za-z0-9_-]{1,64}$/.test(value) ? value : null;
}
