// No frontend writes/config changes or new dependencies. Use installed test tooling.
import { buildSync } from '../../../frontend/node_modules/esbuild/lib/main.js';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const result = buildSync({ entryPoints: [fileURLToPath(new URL('./paper_http_mapping.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false });
const run = spawnSync(process.execPath, ['-'], { input: result.outputFiles[0].text, encoding: 'utf8' });
process.stdout.write(run.stdout ?? '');
process.stderr.write(run.stderr ?? '');
process.exitCode = run.status ?? 1;
