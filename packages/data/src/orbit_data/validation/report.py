"""Offline, self-contained inspection page. All untrusted values use textContent."""

import json
from pathlib import Path

PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orbit · Connector 验证</title><style>
:root{font:15px/1.5 system-ui,sans-serif;color:#e4e8ee;background:#14181e}body{max-width:1180px;margin:auto;padding:32px}h1{font-size:28px;margin:0}p{color:#b6c1d1}header{margin-bottom:26px}table{width:100%;border-collapse:collapse;background:#1c222c}th,td{text-align:left;padding:11px;border-bottom:1px solid #303a47}select,button{background:#263340;color:inherit;border:1px solid #60758c;padding:8px;border-radius:5px;margin:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1c222c;padding:16px;border-radius:6px;font:13px/1.6 ui-monospace,monospace}article{display:grid;grid-template-columns:1fr 1fr;gap:18px}.events{max-height:65vh;overflow:auto}.event{cursor:pointer;padding:12px;border-bottom:1px solid #38414c}.event:hover{background:#253445}.kind{font:12px monospace;color:#8fc8ff}.text{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#96a7ba}.pass{color:#9dd8ae}.gap{color:#efc17c}h2{font-size:19px;margin-top:28px}@media(max-width:760px){article{grid-template-columns:1fr}body{padding:18px}table{font-size:12px}}
</style><header><h1>Orbit · 数据导入与标准化验证</h1><p>本地离线报告 · L0 原始归档 → L1 逐记录记账 → L2 标准事件 → L3 分析表</p><small id="boundary"></small></header>
<table><thead><tr><th>来源</th><th>验证范围</th><th>状态</th><th>L1 / L2</th><th>首次 / 重复扫描</th></tr></thead><tbody id="results"></tbody></table>
<h2>会话与事件检查</h2><p>选择一条事件查看规范字段、原始记录 ID 和派生数据。这里只展示有界预览；完整证据保存在本机数据库及 raw 目录。</p><select id="session"></select><article><div id="events" class="events"></div><div><pre id="detail">选择左侧事件</pre><pre id="derived"></pre></div></article>
<h2>完整验证摘要</h2><pre id="summary"></pre>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const el=id=>document.getElementById(id);
el('boundary').textContent=data.boundary;
for(const r of data.results){const tr=document.createElement('tr');const cells=[r.agent+(r.label?' · '+r.label:''),r.mode,r.status,`${r.records??'—'} / ${r.events??'—'}`,r.cold_seconds===undefined?'—':`${r.cold_seconds}s / ${r.warm_seconds}s`];for(const text of cells){const td=document.createElement('td');td.textContent=text;tr.append(td)}tr.className=r.status.startsWith('passed')?'pass':'gap';el('results').append(tr)}
for(const [i,s] of data.sessions.entries()){const opt=document.createElement('option');opt.value=i;opt.textContent=`${s.agent} / ${s.mode} / ${s.title||s.native_id}`;el('session').append(opt)}
function render(){const s=data.sessions[Number(el('session').value)];el('events').replaceChildren();if(!s)return;el('derived').textContent=JSON.stringify(s.derived,null,2);for(const e of s.events){const row=document.createElement('div');row.className='event';const kind=document.createElement('div');kind.className='kind';kind.textContent=`#${e.seq}  ${e.kind}  ${e.ts===null?'时间未知':new Date(e.ts).toISOString()}`;const text=document.createElement('div');text.className='text';text.textContent=e.text||e.attrs.name||e.attrs.model_raw||'（结构化记录）';row.append(kind,text);row.onclick=()=>{el('detail').textContent=JSON.stringify(e,null,2)};el('events').append(row)}}el('session').onchange=render;render();el('summary').textContent=JSON.stringify({verification:data.results,benchmark:data.benchmark},null,2);
</script></html>"""


def write_report(path: Path, data: dict):
    encoded = (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    path.write_text(PAGE.replace("__DATA__", encoded), encoding="utf-8")
    path.chmod(0o600)
