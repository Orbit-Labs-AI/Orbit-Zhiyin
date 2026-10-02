// Run with Node.js: node docs/design/demo/check-benchmark.cjs
// Checks the standalone demo's seeded data and all eight views without dependencies.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'tandem-benchmark-demo.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
if (!script) throw new Error('Missing application script');
new vm.Script(script);
const beforeDOMEvents = script.indexOf("document.addEventListener('click'");
if (beforeDOMEvents < 0) throw new Error('Missing application event boundary');
const diagnostics = `
let checks = 0, emptyScopes = 0;
for (const range of [7, 30, 90, 0]) {
  for (const agent of ['all', ...AG.map(a => a.id)]) {
    for (const project of ['all', ...PJ.map(p => p.id)]) {
      S.range = range; S.agent = agent; S.project = project;
      const list = filtered(), st = stats(list), rows = toolsFor(list);
      if (sum(rows, t => t.n) !== st.tools || sum(rows, t => t.errors) !== st.errors)
        throw Error('Tool totals do not reconcile');
      if (st.corr > st.msgs || st.errors > st.tools || !Number.isFinite(st.fric))
        throw Error('Invalid aggregate');
      if (rows.some(t => t.errors > t.n)) throw Error('Tool errors exceed calls');
      const sessions = matchingSessions();
      if (sessions.some((s, i) => i && s.end > sessions[i - 1].end))
        throw Error('Sessions are not sorted by last chat time');
      if (list.some(s => (agent !== 'all' && s.a !== agent) || (project !== 'all' && s.p !== project)))
        throw Error('Filter scope mismatch');
      for (const renderPage of Object.values(PAGES)) {
        if (/NaN|undefined|Infinity/.test(renderPage())) throw Error('Invalid view output');
      }
      if (!list.length) emptyScopes++;
      checks++;
    }
  }
}
({ filterCombinations: checks, emptyScopes, sessions: ALL.filter(s => s.d <= 119 && !s.live).length, routes: Object.keys(PAGES).length });
`;
const result = vm.runInNewContext(script.slice(0, beforeDOMEvents) + diagnostics, {
  document: {}, localStorage: { getItem() { return null; } },
  URLSearchParams, location: { hash: '' }
});
console.log(JSON.stringify(result, null, 2));
