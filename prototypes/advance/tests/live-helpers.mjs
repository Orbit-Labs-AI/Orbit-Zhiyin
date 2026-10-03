// Live-mode test harness shared by every live-<slice>.spec.mjs (owned by slice 0).
//   const gw = await stubGateway(page, 'core');                    // prototypes/shared/fixtures/core/routes.json
//   const gw = await stubGateway(page, ['core', 'tools'], { 'GET /v1/uiview/tools': { status: 404 } });
//   await openLive(page, 'tools');                                 // http://orbit.test/app?live=1#tools
// Fixture map values: a file name (in the fixture folder), a JSON body, {status, body, headers, delay}, or (req, url) => one of those.
// gw.set(key, value) swaps an answer mid-test, gw.push(frames) queues SSE frames for the next /v1/events connection,
// gw.seen lists every request ({method, path, query, auth}).
// LIVE_GATEWAY=http://127.0.0.1:<port> ORBIT_TOKEN=<token> switches /v1/* to a pass-through proxy (no CORS: the page still
// runs on http://orbit.test); /v1/events and other …/stream SSE paths then answer an empty stream so the test never hangs on a live SSE connection.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, '..', '..');
export const FIXTURES = path.join(ROOT, 'shared', 'fixtures');
export const ADV_FILE = path.join(ROOT, 'advance', 'orbit-demo.html');
export const ORIGIN = 'http://orbit.test';
export const PASS = process.env.LIVE_GATEWAY ? process.env.LIVE_GATEWAY.replace(/\/+$/, '') : null;
export const fx = (rel) => JSON.parse(fs.readFileSync(path.join(FIXTURES, rel), 'utf8'));
export const sseText = (frames) => frames.map((f, i) => 'id: ' + (f.id != null ? f.id : i + 1) + '\nevent: ' + f.event + '\ndata: ' + JSON.stringify(f.data || {}) + '\n\n').join('');

function loadDir(dir) {
  const base = path.join(FIXTURES, dir);
  const man = JSON.parse(fs.readFileSync(path.join(base, 'routes.json'), 'utf8'));
  const out = {};
  Object.keys(man).filter((k) => k[0] !== '_').forEach((k) => { out[k] = JSON.parse(fs.readFileSync(path.join(base, man[k]), 'utf8')); });
  return out;
}

export async function stubGateway(page, dirs, extra, opts) {
  opts = opts || {};
  const map = {};
  [].concat(dirs || []).forEach((d) => Object.assign(map, loadDir(d)));
  Object.assign(map, extra || {});
  const state = { seen: [], queue: [], map };
  state.set = (k, v) => { map[k] = v; };
  state.push = (frames) => { state.queue.push(frames); };
  state.count = (p) => state.seen.filter((x) => x.path === p).length;
  const token = opts.token || process.env.ORBIT_TOKEN || 'test-token';
  await page.addInitScript(([o, t, nat]) => {
    window.__ORBIT_ENDPOINT__ = o; window.__ORBIT_TOKEN__ = t;
    if (nat) {
      window.__ORBIT_NATIVE__ = nat;
      window.__nativeMsgs = []; window.__dragRegions = [];
      // dragRegions (23-native-drag.js) is a layout report, kept apart so the op / reply assertions see only bridge calls
      window.webkit = { messageHandlers: { orbit: { postMessage: (m) => (m && m.type === 'dragRegions' ? window.__dragRegions : window.__nativeMsgs).push(JSON.parse(JSON.stringify(m))) } } };
    }
  }, [ORIGIN, token, opts.native || null]);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/^http:\/\/orbit\.test\//, async (route) => {
    const req = route.request(); const u = new URL(req.url());
    state.seen.push({ method: req.method(), path: u.pathname, query: u.search, auth: req.headers().authorization || null });
    if (u.pathname === '/app' || u.pathname === '/app/') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(ADV_FILE, 'utf8') });
    // pass-through: long-lived SSE streams (/v1/events, …/stream) answer an empty stream so route.fetch never waits on them
    if (PASS && /\/stream$/.test(u.pathname)) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    if (u.pathname === '/v1/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: PASS ? '' : sseText(state.queue.shift() || []) });
    if (PASS && u.pathname.startsWith('/v1/')) {
      const res = await route.fetch({ url: PASS + u.pathname + u.search, headers: Object.assign({}, req.headers(), { authorization: 'Bearer ' + token }) });
      return route.fulfill({ response: res });
    }
    let v = map[req.method() + ' ' + u.pathname];
    if (typeof v === 'function') v = await v(req, u);
    if (v === undefined) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'not_found', message: 'no fixture for ' + u.pathname, retryable: false } }) });
    const full = v && typeof v === 'object' && !Array.isArray(v) && ('status' in v || 'body' in v) && Object.keys(v).every((k) => ['status', 'body', 'headers', 'delay'].includes(k)) ? v : { body: v };
    if (full.delay) await new Promise((r) => setTimeout(r, full.delay));
    const status = full.status || 200;
    return route.fulfill({ status, contentType: 'application/json', headers: full.headers || {}, body: full.body === undefined ? (status >= 400 ? JSON.stringify({ error: { code: 'http_' + status, message: 'HTTP ' + status } }) : '') : JSON.stringify(full.body) });
  });
  return state;
}

export function collectErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/fonts\.(googleapis|gstatic)\.com/.test(m.location().url || '') && !/status of 404|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  return errors;
}

// opens /app in live mode; resolves once the spine left 'connecting' (hydrated, empty, computing or error)
export async function openLive(page, hash, query) {
  await page.goto(ORIGIN + '/app?live=1' + (query ? '&' + query : '') + (hash ? '#' + hash : ''));
  await expect(page.locator('#main')).not.toBeEmpty();
  await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).not.toBe('connecting');
}
