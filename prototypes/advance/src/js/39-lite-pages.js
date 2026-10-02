/* ============ Lite edition pages (l-home / l-persona / l-sessions / l-recs) ============ */
// Placeholder pages; the Lite design lands here (owned by the Lite task).
LITE_ROUTES.forEach((r) => {
  PAGES[r[0]] = () => tbar(r[1], rangeLabel()) + '<div class="content" id="content"><div class="card pad" style="margin-top:16px">Lite · ' + r[1] + '</div></div>';
});
