#!/usr/bin/env node
// Evaluates the prototype's persona (15-derive.js personaCompose, the same code the App runs in demo and live mode) on
// facts wire rows, for the backend parity test (tests/integration/test_persona_parity_contract.py).
//
//   node prototypes/advance/tools/persona-eval.mjs < cases.json > out.json
//
// stdin: {"cases": [{"name", "rows": [wire row, …], "agents": [[agent id, …], …]?}]} — rows as GET /v1/uiview/facts
// decodes them (id, d = YYYY-MM-DD, a, msgs, corr, dk, dn, vk, ik, kn, op, ol, oa, os, sc, rb, t0, t1).
// stdout: {"cases": [{"name", "all": persona, "subsets": [persona, …]}]}.
// Rows go through the App's own mapping, not a copy: psRowFields (15-derive.js, which LV.hydrate calls for every row) and
// the backend → UI agent map (the LV_AGENTS / lvAgentOf block of 90-live-core.js, evaluated verbatim), so an alias that
// merges two backend agents or a change to the row mapping shows up here. Day index from d as in LV.hydrate.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'js');
const FILES = ['00-utils.js', '05-data.js', '15-derive.js'];
const win = { addEventListener() {}, localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} } };
const ctx = vm.createContext({ console, window: win, localStorage: win.localStorage });
// the agent map block of 90-live-core.js (the rest of that file needs the live transport and DOM)
const core = fs.readFileSync(path.join(JS, '90-live-core.js'), 'utf8');
const a0 = core.indexOf('/* ---- agent map'), a1 = core.indexOf('/* ---- LV ---- */');
if (a0 < 0 || a1 < a0) throw new Error('90-live-core.js: agent map block not found');
vm.runInContext(FILES.map((f) => fs.readFileSync(path.join(JS, f), 'utf8')).join('\n;\n') + '\n;\n' + core.slice(a0, a1) +
  '\n;globalThis.__persona = { personaCompose, psRowFields, lvAgentOf };', ctx);
const { personaCompose, psRowFields, lvAgentOf } = ctx.__persona;

const DAY = 86400000;
function hydrateRows(rows) {
  const first = rows.reduce((m, r) => (r.d && (!m || r.d < m) ? r.d : m), null);
  const day0 = first ? Date.parse(first + 'T00:00:00Z') : 0;
  return rows.filter((r) => r.d && !r.excluded).map((r) => Object.assign({
    id: r.id, d: Math.round((Date.parse(r.d + 'T00:00:00Z') - day0) / DAY), a: lvAgentOf(r.a).id, p: r.p || '_none'
  }, psRowFields(r)));
}
const plain = (p) => JSON.parse(JSON.stringify({
  ok: p.ok, n: p.n, days: p.days, code: p.code || null, conf: p.conf, consistency: p.consistency == null ? null : p.consistency,
  decided_axes: p.decided_axes || 0,
  axes: (p.axes || []).map((a) => ({ k: a.k, value: a.value, lo: a.lo, hi: a.hi, letter: a.letter, state: a.state, strong: a.strong,
    n_units: a.n_units, k_units: a.k_units, agree: a.agree, decided: a.decided,
    signals: a.signals.map((s) => ({ key: s.key, weight: s.weight, score: s.score, n: s.n })) }))
}));

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = input.cases.map((c) => {
  const L = hydrateRows(c.rows);
  return { name: c.name, all: plain(personaCompose(L)),
    subsets: (c.agents || []).map((ids) => { const ui = ids.map((x) => lvAgentOf(x).id); return plain(personaCompose(L.filter((s) => ui.includes(s.a)))); }) };
});
process.stdout.write(JSON.stringify({ cases: out }));
