// Builds the single-file demo from src/: styles/*.css and js/*.js are concatenated in file-name order
// into src/index.html. Usage:
//   node build.mjs                      -> tandem-demo.html (standalone, open directly in a browser)
//   node build.mjs --out <file>         -> standalone build at <file> (for parallel test runs)
//   node build.mjs --artifact <file>    -> artifact body (doctype/html/head/body lines stripped)
//   node build.mjs --check              -> exit 1 if tandem-demo.html is not up to date
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.join(here, 'src');
const cat = (sub, ext) => fs.readdirSync(path.join(src, sub)).filter((f) => f.endsWith(ext)).sort()
  .map((f) => { const t = fs.readFileSync(path.join(src, sub, f), 'utf8'); return t.endsWith('\n') ? t : t + '\n'; }).join('');

export function build() {
  const tpl = fs.readFileSync(path.join(src, 'index.html'), 'utf8');
  return tpl.replace('/*@css*/\n', () => cat('styles', '.css')).replace('/*@js*/\n', () => cat('js', '.js'));
}

const STRIP = /^(<!doctype html>|<html[^>]*>|<\/?head>|<body>|<\/body>|<\/html>)$/i;
const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const html = build();
if (args.includes('--check')) {
  const cur = fs.readFileSync(path.join(here, 'tandem-demo.html'), 'utf8');
  if (cur !== html) { console.error('tandem-demo.html is stale: run node build.mjs'); process.exit(1); }
  console.log('tandem-demo.html is up to date');
} else if (opt('--artifact')) {
  fs.writeFileSync(opt('--artifact'), html.split('\n').filter((l) => !STRIP.test(l.trim())).join('\n'));
  console.log('artifact ->', opt('--artifact'));
} else {
  const out = opt('--out') || path.join(here, 'tandem-demo.html');
  fs.writeFileSync(out, html);
  console.log('built ->', path.relative(process.cwd(), out) || out, '(' + Math.round(html.length / 1024) + ' KB)');
}
