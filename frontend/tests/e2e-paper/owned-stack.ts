/** Test runner owns private IPC; NONE of this module is imported by the app. */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { cpSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { z } from "zod";

const root = resolve(process.cwd(), "..");
const frontend = join(root, "frontend");
const record = z.record(z.string(), z.unknown());
const ready = z.object({ ready: z.literal(true), accountId: z.string(), foreignId: z.string(), credential: z.string(), postgresVersion: z.string() });
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

async function waitHealth(url: string, child: ChildProcessWithoutNullStreams) {
  for (let attempt = 0; attempt < 300; attempt++) {
    if (child.exitCode !== null) throw new Error("Owned runtime exited before ready");
    try { if ((await fetch(url)).ok) return; } catch {}
    await delay(100);
  }
  throw new Error("Owned runtime readiness deadline exceeded");
}
async function terminate(child: ChildProcessWithoutNullStreams | null) {
  if (!child || child.exitCode !== null) return;
  const exited = new Promise<void>(resolve => child.once("exit", () => resolve()));
  child.kill();
  await Promise.race([exited, delay(10_000)]);
  if (child.exitCode === null && child.signalCode === null) throw new Error("Owned runtime failed to stop");
}

export class OwnedPaperStack {
  accountId = "";
  foreignId = "";
  postgresVersion = "";
  private credential = "";
  private next: ChildProcessWithoutNullStreams | null = null;
  private serial = 0;
  private pending = new Map<number, { resolve: (value: Record<string, unknown>) => void; reject: (reason: Error) => void }>();
  private backend: ChildProcessWithoutNullStreams;
  private readyPromise: Promise<void>;
  constructor() {
    if (!process.env.PAPER_E2E_DATABASE_URL) throw new Error("Real owned PAPER_E2E_DATABASE_URL required; no SQLite/fixture fallback");
    this.backend = spawn(join(root, "backend/.venv/Scripts/python.exe"), [join(frontend, "tests/e2e-paper/owned_backend.py")], {
      cwd: root, windowsHide: true, stdio: "pipe", env: { ...process.env, PYTHONUTF8: "1" },
    });
    this.readyPromise = new Promise((resolveReady, rejectReady) => {
      let buffer = ""; let initialized = false;
      this.backend.stdout.on("data", chunk => {
        buffer += chunk.toString();
        let newline;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
          try {
            const parsed: unknown = JSON.parse(line);
            if (!initialized) {
              const config = ready.parse(parsed); initialized = true;
              this.accountId = config.accountId; this.foreignId = config.foreignId;
              this.credential = config.credential; this.postgresVersion = config.postgresVersion;
              resolveReady();
            } else {
              const response = record.parse(parsed); const id = z.number().parse(response.id);
              const pending = this.pending.get(id); this.pending.delete(id);
              if (response.ok === true) pending?.resolve(response);
              else pending?.reject(new Error("Private test orchestration failed; details withheld"));
            }
          } catch { rejectReady(new Error("Private bootstrap protocol invalid; contents withheld")); }
        }
      });
      this.backend.on("exit", () => {
        rejectReady(new Error("Owned backend exited"));
        for (const pending of this.pending.values()) pending.reject(new Error("Owned backend exited"));
      });
    });
    // Never echo private bootstrap stdout. Stderr is also withheld on failure.
    this.backend.stderr.resume();
  }
  async start() {
    try {
      await Promise.race([this.readyPromise, delay(45_000).then(() => { throw new Error("Private backend bootstrap timed out"); })]);
      await waitHealth("http://127.0.0.1:8014/api/v1/health", this.backend);
      this.assertSecretNotInBundle();
      await this.startFrontend();
      return this;
    } catch (error) { await this.stop(); throw error; }
  }
  private assertSecretNotInBundle() {
    const scan = (directory: string) => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) scan(path);
        else if (readFileSync(path).includes(Buffer.from(this.credential))) throw new Error("Credential found in public build");
      }
    };
    scan(join(frontend, ".next/static"));
  }
  private async startFrontend() {
    const standalone = join(frontend, ".next/standalone");
    cpSync(join(frontend, ".next/static"), join(standalone, ".next/static"), { recursive: true });
    cpSync(join(frontend, "public"), join(standalone, "public"), { recursive: true });
    this.next = spawn(process.execPath, [join(standalone, "server.js")], {
      cwd: standalone, windowsHide: true, stdio: "pipe", env: {
        ...process.env, HOSTNAME: "127.0.0.1", PORT: "3014", PAPER_PRODUCT_RUNTIME: "HTTP",
        PAPER_PRIVATE_RUNTIME_ENABLED: "true", PAPER_PRIVATE_ORIGIN: "http://127.0.0.1:3014",
        PAPER_ACCOUNT_ID: this.accountId, PAPER_DEV_BEARER: this.credential,
        BACKEND_API_URL: "http://127.0.0.1:8014", PAPER_BACKEND_API_PREFIX: "/api/v1",
      },
    });
    this.next.stdout.resume(); this.next.stderr.resume();
    await waitHealth("http://127.0.0.1:3014/paper-trading", this.next);
  }
  async command(action: string, args: Record<string, unknown> = {}) {
    const id = ++this.serial;
    const response = new Promise<Record<string, unknown>>((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.backend.stdin.write(JSON.stringify({ id, action, accountId: this.accountId, ...args }) + "\n");
    return Promise.race([response, delay(20_000).then(() => { this.pending.delete(id); throw new Error("Private test command timeout"); })]);
  }
  async newAccount() {
    const response = await this.command("provision");
    this.accountId = z.string().parse(response.accountId);
    await terminate(this.next); this.next = null;
    await this.startFrontend();
  }
  async restartFrontend() { await terminate(this.next); this.next = null; await this.startFrontend(); }
  async directStatus(accountId: string, path = "", method = "GET", body?: unknown, authenticated = true) {
    const response = await fetch(`http://127.0.0.1:8014/api/v1/paper/accounts/${accountId}${path}`, {
      method, headers: { "Content-Type": "application/json", ...(authenticated ? { Authorization: `Bearer ${this.credential}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    return response.status; // No secret/data returned to browser.
  }
  async stop() {
    await terminate(this.next); this.next = null;
    if (this.backend.exitCode === null && this.backend.signalCode === null) {
      try { await this.command("stop"); } finally { this.backend.stdin.end(); }
      for (let attempt = 0; attempt < 200 && this.backend.exitCode === null; attempt++) await delay(100);
      if (this.backend.exitCode === null) await terminate(this.backend);
    }
    this.credential = "";
  }
}
