// Copies the canonical live adapter (prototypes/shared/orbit-live.js) into both prototypes:
//   Advance  src/js/06-live-client.js        (generated file with a header; then run `node build.mjs` in prototypes/advance)
//   Lite     orbit-benchmark-demo.html       (between the @orbit-live:generated begin / end marker lines)
// Usage: node prototypes/shared/sync-live.mjs [--check]   (--check exits 1 when either copy differs from the canonical)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const CANON = path.join(here, 'orbit-live.js');
const ADV = path.join(root, 'advance', 'src', 'js', '06-live-client.js');
const LITE = path.join(root, 'lite', 'orbit-benchmark-demo.html');
const BEGIN = '/* @orbit-live:generated begin — do not edit; run node prototypes/shared/sync-live.mjs */';
const END = '/* @orbit-live:generated end */';
const HEADER = '/* 生成文件：由 prototypes/shared/sync-live.mjs 从 prototypes/shared/orbit-live.js 复制，请勿手改。\n' +
  '   修改共享适配层后运行 node prototypes/shared/sync-live.mjs，再运行 node prototypes/advance/build.mjs。 */\n';

function fail(msg) { console.error('sync-live: ' + msg); process.exit(1); }
const check = process.argv.includes('--check');
const unknown = process.argv.slice(2).filter((a) => a !== '--check');
if (unknown.length) fail('unknown argument(s): ' + unknown.join(' ') + ' (use --check)');

const canon = fs.readFileSync(CANON, 'utf8').replace(/\s+$/, '') + '\n';
// The Lite copy sits inside an inline <script>; check-benchmark.cjs also reads the first <script> up to its closing tag.
if (/<\/script/i.test(canon)) fail('orbit-live.js must not contain a closing script tag');

const advWant = HEADER + canon;
function liteWant(html) {
  const b = html.indexOf(BEGIN), e = html.indexOf(END);
  if (b < 0 || e < 0 || e < b) fail('Lite HTML is missing the @orbit-live:generated marker lines');
  if (html.indexOf(BEGIN, b + 1) >= 0 || html.indexOf(END, e + 1) >= 0) fail('Lite HTML has more than one @orbit-live:generated block');
  return html.slice(0, b) + BEGIN + '\n' + canon + html.slice(e);
}

const advCur = fs.existsSync(ADV) ? fs.readFileSync(ADV, 'utf8') : null;
const liteCur = fs.readFileSync(LITE, 'utf8');
const liteNext = liteWant(liteCur);
if (check) {
  const stale = [];
  if (advCur !== advWant) stale.push(path.relative(root, ADV));
  if (liteCur !== liteNext) stale.push(path.relative(root, LITE));
  if (stale.length) fail('out of date: ' + stale.join(', ') + ' (run node prototypes/shared/sync-live.mjs)');
  console.log('sync-live: Lite and Advance copies match prototypes/shared/orbit-live.js');
} else {
  if (advCur !== advWant) fs.writeFileSync(ADV, advWant);
  if (liteCur !== liteNext) fs.writeFileSync(LITE, liteNext);
  const wrote = [advCur !== advWant && 'advance/src/js/06-live-client.js', liteCur !== liteNext && 'lite/orbit-benchmark-demo.html'].filter(Boolean);
  console.log(wrote.length ? 'sync-live: wrote ' + wrote.join(', ') : 'sync-live: already up to date');
}
