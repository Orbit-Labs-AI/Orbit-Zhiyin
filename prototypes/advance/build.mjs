// Builds the single-file demo from src/: styles/*.css and js/*.js are concatenated in file-name order
// into src/index.html. orbit-demo.html is generated output: edit src/ and rebuild. Usage:
//   node build.mjs                      -> orbit-demo.html (standalone, open directly in a browser)
//   node build.mjs --out <file>         -> standalone build at <file> (for parallel test runs)
//   node build.mjs --artifact <file>    -> artifact body (doctype/html/head/body lines stripped)
//   node build.mjs --check              -> exit 1 if orbit-demo.html is not up to date
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.join(here, 'src');
// The two-digit prefix is the concatenation order; 00-utils.js must stay first because it opens with "use strict".
const NAME = /^\d{2}-[a-z0-9-]+\.(css|js)$/;

function fail(msg) { console.error('build: ' + msg); process.exit(1); }

// Files are joined with one blank line, so trailing blank lines in a source file never change the output.
function cat(sub, ext) {
  const files = fs.readdirSync(path.join(src, sub)).filter((f) => !f.startsWith('.')).sort();
  const bad = files.filter((f) => !NAME.test(f) || path.extname(f) !== ext);
  if (bad.length) fail(`unexpected file(s) in src/${sub}: ${bad.join(', ')} (expected NN-name${ext})`);
  if (!files.length) fail(`src/${sub} is empty`);
  return files.map((f) => fs.readFileSync(path.join(src, sub, f), 'utf8').replace(/\s+$/, '')).join('\n\n') + '\n';
}

// Each placeholder must appear exactly once, alone on its line.
function fill(tpl, marker, body) {
  const hits = tpl.split(marker).length - 1;
  if (hits !== 1) fail(`src/index.html must contain ${marker} exactly once (found ${hits})`);
  const m = tpl.match(new RegExp(marker.replace(/[*/]/g, '\\$&') + '\\r?\\n'));
  if (!m) fail(`${marker} in src/index.html must be followed by a line break`);
  return tpl.replace(m[0], () => body);
}

function build() {
  const tpl = fs.readFileSync(path.join(src, 'index.html'), 'utf8');
  return fill(fill(tpl, '/*@css*/', cat('styles', '.css')), '/*@js*/', cat('js', '.js'));
}

const args = process.argv.slice(2);
const FLAGS = { '--check': false, '--out': true, '--artifact': true };   // flag -> takes a value
const opts = {};
for (let i = 0; i < args.length; i++) {
  const k = args[i];
  if (!(k in FLAGS)) fail(`unknown argument ${k} (use --check, --out <file> or --artifact <file>)`);
  if (FLAGS[k]) { const v = args[++i]; if (!v || v.startsWith('--')) fail(`${k} needs a file path`); opts[k] = v; } else opts[k] = true;
}
if (Object.keys(opts).length > 1) fail('use only one of --check, --out, --artifact');

const STRIP = /^(<!doctype html>|<html[^>]*>|<\/?head>|<body>|<\/body>|<\/html>)$/i;
const html = build();
const kb = (s) => Math.round(Buffer.byteLength(s) / 1024) + ' KB';
if (opts['--check']) {
  const cur = fs.readFileSync(path.join(here, 'orbit-demo.html'), 'utf8');
  if (cur !== html) fail('orbit-demo.html is stale: run node build.mjs');
  console.log('orbit-demo.html is up to date');
} else if (opts['--artifact']) {
  fs.writeFileSync(opts['--artifact'], html.split('\n').filter((l) => !STRIP.test(l.trim())).join('\n'));
  console.log('artifact ->', opts['--artifact']);
} else {
  const out = opts['--out'] || path.join(here, 'orbit-demo.html');
  fs.writeFileSync(out, html);
  console.log('built ->', path.relative(process.cwd(), out) || out, '(' + kb(html) + ')');
}
