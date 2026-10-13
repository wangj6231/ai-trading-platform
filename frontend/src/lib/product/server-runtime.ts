// Imported only by server layout/routes. Never use NEXT_PUBLIC for these settings.
import type { RuntimeSelection } from "./contracts";

export function paperServerConfig(env: NodeJS.ProcessEnv = process.env) {
  const mode = env.PAPER_PRODUCT_RUNTIME ?? "FIXTURE";
  if (mode === "FIXTURE") return { public: { mode: "FIXTURE" } as RuntimeSelection };
  const accountId = env.PAPER_ACCOUNT_ID;
  const credential = env.PAPER_DEV_BEARER;
  let origin: URL | undefined;
  try { origin = new URL(env.PAPER_PRIVATE_ORIGIN ?? ""); } catch { /* Fail closed below. */ }
  if (mode !== "HTTP" || env.PAPER_PRIVATE_RUNTIME_ENABLED !== "true" || !accountId || !/^[A-Za-z0-9_-]{1,128}$/.test(accountId) ||
      !credential || /[\s\r\n]/.test(credential) || credential.length > 4096 || !origin ||
      origin.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) {
    return { public: { mode: "UNAVAILABLE", code: "BOOTSTRAP_REQUIRED" } as RuntimeSelection };
  }
  return { public: { mode: "HTTP", accountId } as RuntimeSelection, accountId, credential, origin: origin.origin };
}
