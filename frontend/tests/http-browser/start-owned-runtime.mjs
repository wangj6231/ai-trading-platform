import { spawn } from 'node:child_process';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readdirSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
const directory = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(directory, '../../..');
const frontend = join(root, 'frontend');
const backendPort = process.env.HTTP_BACKEND_PORT ?? '8013';
const frontendPort = process.env.HTTP_BROWSER_PORT ?? '3013';
const artifact = join(root, 'docs/frontend-paper-http-v1');
mkdirSync(artifact, { recursive: true });
const backend = spawn(join(root, 'backend/.venv/Scripts/python.exe'), [join(directory, 'owned_backend.py')], { cwd: root, env: { ...process.env, PYTHONUTF8: '1' }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
let next;
let buffer = '';
let bootstrapped = false;
backend.stderr.on('data', chunk => process.stderr.write(chunk));
backend.stdout.on('data', async chunk => {
  if (bootstrapped) return; // Never relay raw credential pipe contents.
  buffer += chunk.toString(); const newline = buffer.indexOf('\n'); if (newline < 0) return;
  bootstrapped = true;
  try {
    const config = JSON.parse(buffer.slice(0, newline)); buffer = '';
    function scan(dir) { for (const entry of readdirSync(dir, { withFileTypes: true })) { const path = join(dir, entry.name); if (entry.isDirectory()) scan(path); else { const content = readFileSync(path); if (content.includes(Buffer.from(config.credential)) || content.includes(Buffer.from(`127.0.0.1:${backendPort}`))) throw new Error('Private runtime configuration present in static bundle'); } } }
    scan(join(frontend, '.next/static'));
    writeFileSync(join(artifact, 'owned-backend-checks.json'), JSON.stringify({ authenticatedActualLifespan: true, dependencyOverrides: false, checks: config.checks, credentialInClientBundle: false, backendURLInClientBundle: false, isolatedSQLite: true, preseededObservations: true, executionE2EProven: false }, null, 2));
    for (let attempt = 0; attempt < 100; attempt++) { try { const health = await fetch(`http://127.0.0.1:${backendPort}/api/v1/health`); if (health.ok) break; } catch {} await new Promise(resolve => setTimeout(resolve, 100)); }
    next = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', frontendPort], { cwd: frontend, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PAPER_PRODUCT_RUNTIME: 'HTTP', PAPER_PRIVATE_RUNTIME_ENABLED: 'true', PAPER_PRIVATE_ORIGIN: `http://127.0.0.1:${frontendPort}`, PAPER_ACCOUNT_ID: config.accountId, PAPER_DEV_BEARER: config.credential, BACKEND_API_URL: `http://127.0.0.1:${backendPort}` } });
    next.stdout.pipe(process.stdout); next.stderr.pipe(process.stderr); next.on('exit', code => { backend.kill(); process.exit(code ?? 1); });
  } catch { process.stderr.write('Owned HTTP bootstrap failed; private pipe contents withheld.\n'); backend.kill(); process.exit(1); }
});
backend.on('exit', code => { if (code) { next?.kill(); process.exit(code); } });
function stop() { next?.kill(); backend.kill(); }
process.on('SIGINT', stop); process.on('SIGTERM', stop); process.on('exit', stop);
