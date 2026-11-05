#!/usr/bin/env node
// Runs pen.dev tool calls headless through `pen interactive`, for agents without the Pencil MCP.
//
//   node pen-run.mjs <file.pen> [--read-only] [--prelude helpers.js] <step>...
//
// Each <step> is either a path to a .js file (sent as one `execute` call, so multi-line
// snippets with quotes need no escaping) or a raw tool call such as 'get_style({name:"Soft Bento"})'
// or 'read_skill({path:"execute.md"})'. Steps run in order in one session, so globals set in
// one snippet are visible to the next (data only: functions do not survive, so put shared
// helpers in a --prelude file, which is prepended to every snippet). The document is saved at
// the end, except with --read-only, which writes to a throwaway copy that is then deleted.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const argv = process.argv.slice(2);
const readOnly = argv.includes('--read-only');
let prelude = '';
const rest = [];
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--read-only') continue;
  if (argv[i] === '--prelude') prelude = `${fs.readFileSync(argv[++i], 'utf8')}\n`;
  else rest.push(argv[i]);
}
const [pen, ...steps] = rest;
if (!pen || steps.length === 0) {
  console.error('usage: node pen-run.mjs <file.pen> [--read-only] [--prelude helpers.js] <snippet.js | tool_call(...)>...');
  process.exit(2);
}

const lines = steps.map((s) =>
  s.endsWith('.js') && fs.existsSync(s)
    ? `execute(${JSON.stringify({ description: `Run ${path.basename(s)}`, input: prelude + fs.readFileSync(s, 'utf8') })})`
    : s,
);
lines.push('save()', 'exit()');

const tmp = readOnly ? fs.mkdtempSync(path.join(os.tmpdir(), 'pen-ro-')) : null;
const out = tmp ? path.join(tmp, 'scratch.pen') : pen;
const args = ['interactive', '--out', out];
if (fs.existsSync(pen)) args.splice(1, 0, '--in', pen);

const r = spawnSync('pen', args, { input: `${lines.join('\n')}\n`, encoding: 'utf8', maxBuffer: 1 << 26 });
if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
if (r.error) {
  console.error(`pen-run: could not start pen (${r.error.message}). Install it: npm i -g @pen.dev/cli`);
  process.exit(1);
}
const noise = /Update available|npm i -g|[╭╮╰╯]|^\s*│.*│\s*$|^\s*$/;
console.log(`${r.stdout ?? ''}${r.stderr ?? ''}`.split('\n').filter((l) => !noise.test(l)).join('\n'));
process.exit(r.status ?? 1);
