// Renders promo.html frame by frame on a virtual clock and muxes it with the soundtrack.
//   node promo/render.mjs [--fps 60] [--from 0] [--to <sec>] [--scale 2] [--out file.mp4] [--frames dir]
// Time is fully virtual: Playwright's fake clock drives JS timers/rAF and promo.js pins every CSS animation and
// transition to the same clock before each capture, so cuts land on the beat regardless of machine speed.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const FPS = +opt('--fps', 60), SCALE = +opt('--scale', 2), FROM = +opt('--from', 0);
const out = path.resolve(opt('--out', path.join(here, 'out', 'orbit-promo.mp4')));
const audio = path.join(here, 'out', 'soundtrack.wav');
const framesDir = opt('--frames', null);
// --only 16,20.5,…: capture just the frames at these beats (into --frames) for a quick contact sheet
const ONLY = opt('--only', null)?.split(',').map(Number);
fs.mkdirSync(path.dirname(out), { recursive: true });

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.wav': 'audio/wav', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = 'http://127.0.0.1:' + server.address().port;

const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: SCALE, locale: 'zh-CN', colorScheme: 'light', reducedMotion: 'no-preference' });
await ctx.clock.install({ time: new Date('2026-10-01T15:30:00+08:00') });
await ctx.clock.pauseAt(new Date('2026-10-01T15:30:01+08:00'));   // time moves only through runFor() below
const page = await ctx.newPage();
page.on('pageerror', (e) => console.error('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error('[console]', m.text()); });
await page.goto(base + '/promo/' + (process.env.PROMO_PAGE || 'promo.html') + '?render' + (args.includes('--debug') ? '&debug' : ''));
for (let i = 0; i < 400 && !(await page.evaluate(() => !!window.PROMO && PROMO.ready)); i++) await ctx.clock.runFor(16);
const DUR = +opt('--to', await page.evaluate(() => PROMO.duration));
const BPM = await page.evaluate(() => BPM);
await page.evaluate((t) => PROMO.start(t), FROM);
const cdp = await ctx.newCDPSession(page);

const total = Math.round((DUR - FROM) * FPS);
const ff = framesDir || ONLY ? null : spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
  ...(fs.existsSync(audio) ? ['-ss', String(FROM), '-i', audio] : []),
  '-vf', 'scale=1920:1080:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '14', '-tune', 'animation',
  ...(fs.existsSync(audio) ? ['-c:a', 'aac', '-b:a', '320k', '-shortest'] : []), '-movflags', '+faststart', out], { stdio: ['pipe', 'inherit', 'inherit'] });
if (framesDir) fs.mkdirSync(framesDir, { recursive: true });
const t0 = Date.now();
for (let f = 0; f < total; f++) {
  // whole milliseconds only (runFor rounds up); the remainder carries over so the app never drifts from the frame clock
  const ms = Math.round((f + 1) * 1000 / FPS) - Math.round(f * 1000 / FPS);
  await ctx.clock.runFor(ms);
  await page.evaluate((t) => PROMO.sync(t), FROM + (f + 1) / FPS);
  if (ONLY) { const beat = (FROM + (f + 1) / FPS) * BPM / 60; const hit = ONLY.find((b) => Math.abs(b - beat) < BPM / 60 / FPS / 2 + 1e-9); if (hit === undefined) continue;
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 85 }); fs.writeFileSync(path.join(framesDir, 'b' + hit.toFixed(2).padStart(6, '0') + '.jpg'), Buffer.from(data, 'base64')); continue; }
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 94, optimizeForSpeed: true });
  const buf = Buffer.from(data, 'base64');
  if (framesDir) fs.writeFileSync(path.join(framesDir, String(f).padStart(5, '0') + '.jpg'), buf);
  else if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  if (f % FPS === 0) process.stdout.write(`\r${(FROM + f / FPS).toFixed(0)}s / ${DUR}s  (${((Date.now() - t0) / 1000).toFixed(0)}s elapsed)`);
}
process.stdout.write('\n');
if (ff) { ff.stdin.end(); await new Promise((r) => ff.on('close', r)); console.log('wrote', out); }
await browser.close(); server.close();
