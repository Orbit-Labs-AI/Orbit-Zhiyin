#!/usr/bin/env node
// Evaluates the prototype's persona (15-derive.js personaCompose, the same code the App runs in demo and live mode) on
// facts wire rows, for the backend parity test (tests/integration/test_persona_parity_contract.py).
//
//   node prototypes/advance/tools/persona-eval.mjs < cases.json > out.json
//
// stdin: {"cases": [{"name", "rows": [wire row, …], "agents": [[agent id, …], …]?}]} — rows as GET /v1/uiview/facts
// decodes them (id, d = YYYY-MM-DD, a, msgs, corr, dk, dn, vk, ik, kn, op, ol, oa, os, sc, rb, t0, t1).
// stdout: {"cases": [{"name", "all": persona, "subsets": [persona, …]}]}.
// Rows are mapped with the persona fields of LV.hydrate (90-live-core.js): day index from d, msgs / corr as || 0 with the
// wire row kept as raw (psContrib reads raw.msgs / raw.corr, so unknown stays unknown).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'js');
const FILES = ['00-utils.js', '05-data.js', '15-derive.js'];
const win = { addEventListener() {}, localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} } };
const ctx = vm.createContext({ console, window: win, localStorage: win.localStorage });
vm.runInContext(FILES.map((f) => fs.readFileSync(path.join(JS, f), 'utf8')).join('\n;\n') +
  '\n;globalThis.__persona = { personaCompose, PSIG };', ctx);
const { personaCompose } = ctx.__persona;

const DAY = 86400000;
function hydrateRows(rows) {
  const first = rows.reduce((m, r) => (r.d && (!m || r.d < m) ? r.d : m), null);
  const day0 = first ? Date.parse(first + 'T00:00:00Z') : 0;
  return rows.filter((r) => r.d && !r.excluded).map((r) => ({
    id: r.id, d: Math.round((Date.parse(r.d + 'T00:00:00Z') - day0) / DAY), a: r.a, p: r.p || '_none',
    msgs: r.msgs || 0, corr: r.corr || 0,
    dk: r.dk, dn: r.dn, vk: r.vk, op: r.op, t0: r.t0, t1: r.t1, ik: r.ik, kn: r.kn, ol: r.ol, oa: r.oa, os: r.os, sc: r.sc, rb: r.rb, raw: r
  }));
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
    subsets: (c.agents || []).map((ids) => plain(personaCompose(L.filter((s) => ids.includes(s.a))))) };
});
process.stdout.write(JSON.stringify({ cases: out }));
