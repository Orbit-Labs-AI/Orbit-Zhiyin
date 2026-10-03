/* ============ sample data (all values are examples) ============ */
const AG = [
  { id: 'cc', name: 'Claude Code', short: 'Claude', c: 'var(--a1)', t: 'var(--a1t)', path: '~/.claude/projects', ver: 'v2.1', model: 'claude-opus-5-5 · thinking high', cli: 'claude -p', resume: 'claude --resume', all: 1412 },
  { id: 'cx', name: 'Codex', short: 'Codex', c: 'var(--a2)', t: 'var(--a2t)', path: '~/.codex/sessions', ver: '0.62', model: '默认模型 · reasoning high', cli: 'codex exec', resume: 'codex resume', all: 498 },
  { id: 'km', name: 'Kimi CLI', short: 'Kimi', c: 'var(--a3)', t: 'var(--a3t)', path: '~/.kimi-code/sessions', ver: '0.31', model: '默认模型', cli: 'kimi', resume: 'kimi --session', all: 211 },
  { id: 'ds', name: 'DeepSeek Harness', short: 'DeepSeek', c: 'var(--a4)', t: 'var(--a4t)', path: '~/.dsh/sessions', ver: '1.4', model: '默认模型', cli: 'dsh run', resume: 'dsh resume', all: 160 },
  { id: 'oc', name: 'OpenCode', short: 'OpenCode', c: 'var(--a5)', t: 'var(--a5t)', path: '~/.local/share/opencode', ver: '0.9', model: '默认模型', cli: 'opencode run', resume: 'opencode --session', all: 135 }
];
const AGI = {}; AG.forEach((a, i) => { AGI[a.id] = a; });
const AGF = { cc: 1.05, cx: 0.95, km: 0.82, ds: 0.72, oc: 0.78 };
const AGFR = { cc: 0.85, cx: 1.1, km: 1.55, ds: 1.25, oc: 1.6 };
const TOPICS = { git: 'Git / PR 收尾与仓库规范', design: '产品设计、Demo 与部署', paper: '论文审阅与 LaTeX', data: 'Agent 数据管线', quant: '量化与数据分析', net: '网络代理规则', other: '其他' };
const PJ = [
  { id: 'confluo', name: 'Confluo', path: '~/Projects/ActionMesh AI/Confluo', git: 'ActionMesh-AI/Confluo', q: 38, h: 31, A: 12.4, fr: 10.2, I: 76, V: 66, err: 0.075, tags: ['设计', '演示', '部署'], topics: { design: 0.85, git: 0.15 }, fric: { '方向错误': 5, '改动过度': 3, '并行会话冲突': 1 },
    flow: [['读规格', 'Read ×18'], ['改组件', 'Edit ×9'], ['本地构建', 'npm run build'], ['部署', 'wrangler deploy'], ['线上验证', 'curl -I']], cover: [['AGENTS.md', '2.1 KB', '9/26 更新', 1], ['Hooks', '0', '可加部署守卫', 0], ['Skills', '1', 'design-review', 1], ['MCP', '1', 'browser', 1], ['子代理', '0', '可加发布验收员', 0]], tip: '为部署步骤加「目标平台守卫」Hook，拦截非 Cloudflare 的部署命令', rec: 'deploy-target',
    titles: ['部署 Confluo 演示到自定义域名并验证', '调整卡片手势判定阈值', '整理 v2 设计文档并压缩篇幅', '为 Demo 加深色模式', '制作 88 秒宣传短片', '修复卡片在窄屏的溢出', '生成场景视觉案例', '归档 v1 代码', '对比三种详情页方案', '校对中文题名与 AI 速读'] },
  { id: 'latentskill', name: 'latentskill', path: '~/Research/ppb', git: 'PbX8217/latentskill', q: 31, h: 34, A: 6.1, fr: 5.1, I: 36, V: 82, err: 0.035, tags: ['Python', 'LaTeX', '论文审阅', '数据管线'], topics: { paper: 0.65, data: 0.35 }, fric: { '改动过度': 4, '误解需求': 3, '额度 / 用量中断': 1 },
    flow: [['只读审查', 'Read ×24'], ['归档快照', 'cp → archive/'], ['最小修改', 'Edit ×6'], ['重新编译', 'latexmk'], ['页数检查', '≤ 9 页']], cover: [['AGENTS.md', '3.2 KB', '9/28 更新', 1], ['Hooks', '1', '禁止删 .bib', 1], ['Skills', '0', '可封装审稿流程', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '可加引用核查员', 0]], tip: '添加「改动 .tex 后自动编译并检查页数」的 PostToolUse Hook', rec: 'latex-hook',
    titles: ['审阅 ICLR 稿件第 3 节与代码一致性', '核对论文引用与 BibTeX', 'WebShop 轨迹采集进度检查', '把正文压到 9 页', '复现 accuracy / KL 散点图', '整理 BeliefPair 数据过滤分析', '把审稿意见翻译成中文', '批量采集提速：前缀缓存', '检查 wandb 曲线异常', '写论文蓝图与贡献点'] },
  { id: 'teamhub', name: 'team-hub', path: '~/Projects/ActionMesh AI/team-hub', git: 'ActionMesh-AI/team-hub', q: 24, h: 12, A: 9.8, fr: 6.4, I: 44, V: 60, err: 0.05, tags: ['Obsidian', '协作规则', 'Git'], topics: { git: 1 }, fric: { '流程过重（子代理）': 3, '方向错误': 2, '并行会话冲突': 2 },
    flow: [['同步 collab', 'git pull'], ['审核新增', 'git diff main'], ['整理日报', 'Edit ×4'], ['开 PR', 'gh pr create'], ['回流检查', 'gh run watch']], cover: [['AGENTS.md', '4.8 KB', '9/30 更新', 1], ['Hooks', '1', '阻止新建 CLAUDE.md', 1], ['Skills', '0', '可封装每日审核', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '无需', 0]], tip: '把「每日审核 collab」固定成 Skill，减少每天重复说明', rec: 'pr-wrapup',
    titles: ['同步 team-hub collab 并审核日报', '合并 PR 并清理分支', '统一 AGENTS.md 并删除旧规则文件', '处理 Codex review 意见', '整理项目索引', '清理过期会话与权限'] },
  { id: 'hackathon', name: 'Hackathon', path: '~/Projects/ActionMesh AI/Hackathon', git: 'ActionMesh-AI/Hackathon', q: 22, h: 14, A: 13.5, fr: 9.1, I: 78, V: 64, err: 0.06, tags: ['比赛', '设计', 'Git'], topics: { git: 0.55, design: 0.45 }, fric: { '方向错误': 3, '流程过重（子代理）': 2, '并行会话冲突': 2 },
    flow: [['讨论需求', '3 轮对话'], ['写规则', 'Edit AGENTS.md'], ['开 PR', 'gh pr create'], ['处理 review', '@codex review'], ['合并', 'gh pr merge']], cover: [['AGENTS.md', '2.5 KB', '10/1 更新', 1], ['Hooks', '0', '可加 review 收敛规则', 0], ['Skills', '0', '可加 PR 收尾', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '无需', 0]], tip: '安装 PR 收尾 Skill：最多两轮 review，只修 P0 / P1', rec: 'pr-wrapup',
    titles: ['设计 Orbit Mac App 视觉案例', '合并 PR 并清理分支', '精简 AGENTS.md 规则表述', '初始化仓库结构', '讨论 MVP 范围', '把视觉案例做成交互 Demo'] },
  { id: 'quant', name: 'Auto Finance & Quant', path: '~/Projects/Auto Finance & Quant', git: 'yhyfhgs/Auto-Finance-Quant', q: 18, h: 16, A: 8.2, fr: 7.4, I: 66, V: 70, err: 0.05, tags: ['Python', 'uv', '回测'], topics: { quant: 1 }, fric: { '误解需求': 4, '工具 / 环境失败': 2 },
    flow: [['拉数据', 'datahub sync'], ['清洗', 'pandas'], ['回测', 'pytest -q'], ['出图', 'matplotlib'], ['写结论', 'Edit report.md']], cover: [['AGENTS.md', '1.6 KB', '9/12 更新', 1], ['Hooks', '0', '可加单测守卫', 0], ['Skills', '0', '无需', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '无需', 0]], tip: '改动后自动跑相关单测的 Hook，减少「误解需求」类返工', rec: 'acceptance',
    titles: ['生成因子衰减综述对比表', '回测数据清洗', '整理 datahub 接口', '修复 equity 模块单测', '更新加密套利监控脚本', '写宏观指标看板'] },
  { id: 'fhgs', name: 'FHGS Website', path: '~/Projects/FHGS Website', git: 'yhyfhgs/FHGS-Website', q: 16, h: 13, A: 11.1, fr: 8.0, I: 70, V: 66, err: 0.06, tags: ['Next.js', 'Rust', '部署'], topics: { design: 0.7, git: 0.3 }, fric: { '工具 / 环境失败': 3, '方向错误': 2 },
    flow: [['写文章', 'Edit .mdx'], ['构建', 'pnpm build'], ['部署', 'docker compose'], ['验证', 'curl -I']], cover: [['AGENTS.md', '2.8 KB', '9/20 更新', 1], ['Hooks', '0', '可加构建检查', 0], ['Skills', '0', '无需', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '可加发布验收员', 0]], tip: '发布后用子代理独立验收线上状态码与跳转', rec: 'deploy-target',
    titles: ['发布博客文章到 fhxgs.cc', '修复统计服务内存泄漏', '优化首页加载速度', '迁移 MDX 组件', '配置 Cloudflare Tunnel'] },
  { id: 'surge', name: 'Surge 规则', path: '~/.config/surge', git: '（无 git）', q: 14, h: 9, A: 15.2, fr: 12.6, I: 74, V: 40, err: 0.095, tags: ['网络', '规则', 'CDN'], topics: { net: 1 }, fric: { '工具 / 环境失败': 5, '方向错误': 1 },
    flow: [['审计规则', 'Read ×35'], ['改生成器', 'Edit gen.py'], ['生成', 'python gen.py'], ['发布', 'CDN upload'], ['抽查', 'surge-cli test']], cover: [['AGENTS.md', '—', '未创建', 0], ['Hooks', '0', '可加重复失败熔断', 0], ['Skills', '0', '无需', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '无需', 0]], tip: '安装 retry-breaker：同一命令失败 2 次先检查认证', rec: 'retry-breaker',
    titles: ['修复 Surge 规则生成器漏判', '审计 35 个规则列表', '发布规则到 CDN', '排查 Tailscale 屏幕共享', '新增学术直连规则表'] },
  { id: 'tweet', name: 'Tweet Card', path: '~/Projects/Tweet Card', git: 'yhyfhgs/tweet-card', q: 9, h: 5, A: 7.4, fr: 3.2, I: 68, V: 46, err: 0.04, tags: ['SQLite', '渲染'], topics: { design: 0.5, other: 0.5 }, fric: { '误解需求': 2, '改动过度': 1 },
    flow: [['归档', 'sqlite3'], ['渲染', 'node render'], ['发布', 'pnpm deploy']], cover: [['AGENTS.md', '0.9 KB', '8/30 更新', 1], ['Hooks', '0', '无需', 0], ['Skills', '0', '无需', 0], ['MCP', '0', '无需', 0], ['子代理', '0', '无需', 0]], tip: '这个项目协作很顺，可以作为写规则的参照', rec: 'acceptance',
    titles: ['归档推文到 SQLite', '调整卡片渲染样式', '静态发布推文卡片', '修复长推文截断'] },
  { id: 'other', name: '其他文件夹', path: '~/Research · ~/Downloads …', git: '（多个）', q: 14, h: 8, A: 9, fr: 6, I: 60, V: 58, err: 0.05, tags: ['零散任务'], topics: { other: 0.6, data: 0.4 }, fric: { '误解需求': 2, '工具 / 环境失败': 1 },
    flow: [['读材料', 'Read'], ['整理', 'Edit'], ['导出', 'Write']], cover: [['AGENTS.md', '—', '各目录不同', 0], ['Hooks', '0', '—', 0], ['Skills', '0', '—', 0], ['MCP', '0', '—', 0], ['子代理', '0', '—', 0]], tip: '零散目录建议并入对应项目，统计会更准', rec: 'acceptance',
    titles: ['整理下载目录', '咖啡数据回归分析', '读论文并写笔记', '量化因子衰减综述溯源', '配置新机器环境'] }
];
const PJI = {}; PJ.forEach((p) => { PJI[p.id] = p; });
// sidebar user row (25-nav sideFoot): the demo persona; live mode (90-live-core) swaps in a neutral local-user label
const ME = { name: 'yhyfhgs', av: 'yh' };
const AFF = {
  cc: { confluo: 5, latentskill: 4, teamhub: 2, hackathon: 4, quant: 2, fhgs: 3, surge: 1, tweet: 1, other: 2 },
  cx: { confluo: 1, latentskill: 2, teamhub: 4, hackathon: 2, quant: 3, fhgs: 2, surge: 4, tweet: 2, other: 1 },
  km: { confluo: 0.4, latentskill: 5, teamhub: 0.5, hackathon: 0.5, quant: 1, fhgs: 0.5, surge: 0.3, tweet: 0.5, other: 3 },
  ds: { confluo: 0.3, latentskill: 5, teamhub: 0.3, hackathon: 0.3, quant: 1, fhgs: 0.3, surge: 0.5, tweet: 0.3, other: 2 },
  oc: { confluo: 0.5, latentskill: 0.5, teamhub: 0.5, hackathon: 0.5, quant: 4, fhgs: 3, surge: 0.5, tweet: 4, other: 1 }
};
let DAY0 = Date.UTC(2026, 5, 3);   // live mode (90-live-core) moves DAY0 / LASTDAY to the real calendar
let LASTDAY = 119;
let FIRSTDAY = 0;   // first day of the 全部 window: mock 0; live = the earliest session's day (R4-04)
const dayDate = (d) => new Date(DAY0 + d * 86400000);
const wd = (d) => (new Date(DAY0 + d * 86400000).getUTCDay() + 6) % 7;   // 0 = Monday
const WD = ['一', '二', '三', '四', '五', '六', '日'];
const md = (d) => { const x = dayDate(d); return (x.getUTCMonth() + 1) + '/' + x.getUTCDate(); };
const mdz = (d) => { const x = dayDate(d); return (x.getUTCMonth() + 1) + ' 月 ' + x.getUTCDate() + ' 日'; };
const hm = (h, m) => String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
const dur = (m) => m >= 60 ? Math.floor(m / 60) + 'h' + String(Math.round(m % 60)).padStart(2, '0') + 'm' : Math.round(m) + 'm';
const HW = [0.42, 0.22, 0.08, 0.03, 0.01, 0.01, 0.03, 0.1, 0.3, 0.55, 0.85, 0.95, 0.6, 0.55, 0.8, 0.92, 0.88, 0.75, 0.5, 0.55, 0.8, 0.95, 0.92, 0.7];
const SEP = [[4,1,0,0,2],[5,1,1,0,1],[3,1,1,1,0],[4,2,1,0,0],[2,1,0,0,0],[1,1,0,0,0],[4,1,1,0,0],[4,2,1,0,0],[5,2,1,1,0],[6,1,0,1,0],[4,1,0,0,1],[3,1,0,0,0],[2,1,0,0,0],[4,2,1,0,0],[4,2,0,1,1],[4,2,1,0,0],[7,0,0,1,1],[6,2,1,1,1],[2,1,1,0,0],[1,1,0,0,0],[3,0,1,1,1],[5,1,1,0,0],[5,1,0,1,1],[4,3,1,1,0],[4,2,0,1,0],[2,1,0,0,0],[1,1,0,0,0],[4,1,0,1,0],[4,1,0,1,0],[5,1,1,1,0]];
const TYPES = {
  DPMV: ['总设计师', 'The Master Planner', '胸有蓝图的统筹者，规格先行、多线分派、件件验收，再大的项目也井井有条。'],
  DPMT: ['调度官', 'The Dispatcher', '果断高效的组织者，把需求讲清就放手并行，善于授权，让产出源源不断。'],
  DPFV: ['监制', 'The Producer', '专注严谨的把关人，一次只推一件事，交代清楚、严格验收，出品稳定可靠。'],
  DPFT: ['策划人', 'The Strategist', '思路清晰的出题人，擅长把想法写成好任务书，放心交付，把精力留给关键判断。'],
  DIMV: ['指挥家', 'The Conductor', '统揽全局的领军人，多个 Agent 齐头并进，亲自守住验收，速度与质量兼得。'],
  DIMT: ['冲浪者', 'The Surfer', '敏锐灵活的弄潮儿，同时驾驭多条线、顺势快速迭代，总能在变化中抓住机会。'],
  DIFV: ['探路者', 'The Pathfinder', '敢闯又踏实的开拓者，让 Agent 先行探索、一路走深，再亲自核实每一步。'],
  DIFT: ['远航者', 'The Voyager', '好奇开放的旅人，给 Agent 充分的发挥空间，享受一路上的意外之喜。'],
  SPMV: ['飞控官', 'The Mission Controller', '冷静缜密的全局掌控者，多条线同时推进也步步有令、逐项核对，让每条线都稳稳落地。'],
  SPMT: ['杂技师', 'The Juggler', '精力充沛的多面手，计划周全、亲自操盘多件事，节奏明快，推进效率惊人。'],
  SPFV: ['分析学家', 'The Analyst', '冷静理性的思考者，先想清楚再动手，亲自掌舵、单线深挖、步步求证，结论经得起推敲。'],
  SPFT: ['领航员', 'The Navigator', '条理分明的引路人，把步骤一条条讲清楚，Agent 照着执行就能精准抵达。'],
  SIMV: ['实验家', 'The Experimenter', '不拘一格的尝鲜派，同时尝试几种做法、边做边改，用结果找到更优解。'],
  SIMT: ['即兴乐手', 'The Jammer', '灵感充沛的创作者，和多个 Agent 快速往来、彼此激发，擅长打开新思路。'],
  SIFV: ['雕刻师', 'The Sculptor', '耐心细致的打磨者，小步尝试、即时查看、反复修改，一点点刻出理想的形状。'],
  SIFT: ['同行者', 'The Companion', '默契十足的协作伙伴，像结对编程一样边聊边推进，彼此信任、配合流畅。']
};
const AXES = [
  { k: 'D', L: 'D', Ln: '委托', R: 'S', Rn: '掌舵', dim: '委托', q: '你把多大块的事交出去？', sig: '每会话消息数 · 单轮自主步数 · 打断与中止率' },
  { k: 'I', L: 'P', Ln: '规划', R: 'I', Rn: '即兴', dim: '即兴', q: '先想清楚再动手，还是边做边想？', sig: '首条消息长度与验收标准 · 规格文件引用 · 中途改向' },
  { k: 'M', L: 'M', Ln: '多线', R: 'F', Rn: '专注', dim: '多线', q: '你同时推进几件事？', sig: '每日会话数 · 同日使用的 Agent 数 · 子代理并行度' },
  { k: 'V', L: 'V', Ln: '求证', R: 'T', Rn: '信任', dim: '求证', q: '你怎么确认它做对了？', sig: '要求测试 / 编译 / 线上验证的比例 · 回滚与重做率' }
];

function pickW(r, w) { let tot = 0; for (const k in w) tot += w[k]; let x = r() * tot; for (const k in w) { x -= w[k]; if (x <= 0) return k; } return Object.keys(w)[0]; }
function poisson(lam, r) { const L = Math.exp(-lam); let k = 0, p = 1; do { k++; p *= r(); } while (p > L && k < 30); return k - 1; }
function largestRemainder(weights, total) {
  const s = weights.reduce((a, b) => a + b, 0) || 1;
  const raw = weights.map((w) => (w / s) * total); const fl = raw.map(Math.floor);
  let rem = total - fl.reduce((a, b) => a + b, 0);
  raw.map((v, i) => [v - fl[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (rem > 0) { fl[i]++; rem--; } });
  return fl;
}
const FEAT_ID = 'sess-0930-1402';
function genSessions() {
  const r = rng(20261001);
  const hsum = HW.reduce((a, b) => a + b, 0);
  const hourPick = () => { let x = r() * hsum; for (let h = 0; h < 24; h++) { x -= HW[h]; if (x <= 0) return h; } return 23; };
  const mk = (d, a, p, aMul) => {
    const P = PJI[p];
    const dm = 6 + Math.pow(r(), 1.5) * 110;
    const msgs = Math.max(1, Math.round(2 + dm / 9 + r() * 4));
    const A = P.A * aMul * (0.85 + r() * 0.3) * AGF[a];
    const tools = Math.max(1, Math.round((msgs * A) / 1.54));
    return { d, a, p, h: hourPick(), mi: Math.floor(r() * 60), dur: dm, msgs, tools, errors: Math.round(tools * P.err * (0.5 + r())), corr: poisson((msgs * P.fr / 100) * AGFR[a], r), lam: (msgs * P.fr / 100) * AGFR[a] };
  };
  const out = [];
  for (let d = 0; d < 90; d++) {
    const mo = d < 28 ? 0 : d < 59 ? 1 : 2;
    const weekend = wd(d) >= 5;
    const base = [[2.6, 1], [2.7, 1.1], [5.6, 2.2]][mo][weekend ? 1 : 0];
    const n = Math.max(0, Math.round(base + (r() - 0.5) * 2));
    const amix = [{ cc: 0.55, cx: 0.35, km: 0.1 }, { cc: 0.55, cx: 0.3, km: 0.1, ds: 0.05 }, { cc: 0.6, cx: 0.22, km: 0.08, ds: 0.06, oc: 0.04 }][mo];
    const pw = [{ latentskill: 5, quant: 4, tweet: 3, other: 2, fhgs: 3, confluo: 2 }, { latentskill: 4, quant: 3, confluo: 4, fhgs: 3, surge: 2, other: 2 }, { confluo: 5, hackathon: 1, latentskill: 3, teamhub: 3, surge: 3, quant: 2, fhgs: 2, other: 2 }][mo];
    for (let i = 0; i < n; i++) {
      const a = pickW(r, amix);
      const w = {}; for (const p in pw) w[p] = pw[p] * (AFF[a][p] || 0.5);
      out.push(mk(d, a, pickW(r, w), [0.68, 1.08, 0.95][mo]));
    }
  }
  const quota = {}; PJ.forEach((p) => { quota[p.id] = p.q; }); quota.confluo--;
  const slots = [];
  SEP.forEach((row, i) => row.forEach((n, j) => { for (let k = 0; k < n; k++) slots.push({ d: 90 + i, a: AG[j].id }); }));
  slots.splice(slots.findIndex((s) => s.d === 119 && s.a === 'cc'), 1);
  const ord = { oc: 0, ds: 1, km: 2, cx: 3, cc: 4 };
  slots.sort((x, y) => ord[x.a] - ord[y.a] || x.d - y.d);
  const sep = [];
  slots.forEach((s) => {
    let best = null, bv = -1;
    PJ.forEach((p) => { if (quota[p.id] <= 0) return; const v = (AFF[s.a][p.id] || 0.3) * quota[p.id] * (0.6 + r() * 0.8); if (v > bv) { bv = v; best = p.id; } });
    quota[best]--; sep.push(mk(s.d, s.a, best, 1));
  });
  const FEAT = { id: FEAT_ID, d: 119, a: 'cc', p: 'confluo', h: 14, mi: 2, dur: 42, msgs: 7, tools: 142, errors: 9, corr: 2, out: 'ok', verify: true, title: '部署 Confluo 演示到自定义域名并验证', featured: true, mood: -0.05, topic: 'design', fric: '方向错误' };
  PJ.forEach((p) => {
    const L = sep.filter((s) => s.p === p.id);
    const target = p.h * 60 - (p.id === 'confluo' ? 42 : 0);
    const cur = sum(L, (s) => s.dur);
    L.forEach((s) => { s.dur = Math.max(3, s.dur * target / cur); });
  });
  const fitTotal = (key, total, wfn) => { const v = largestRemainder(sep.map(wfn), total); sep.forEach((s, i) => { s[key] = Math.max(key === 'errors' || key === 'corr' ? 0 : 1, v[i]); }); };
  fitTotal('msgs', 1284 - 7, (s) => s.msgs);
  fitTotal('tools', 9860 - 142, (s) => s.tools);
  fitTotal('errors', 614 - 9, (s) => s.errors + 0.3);
  PJ.forEach((p) => {
    const L = sep.filter((s) => s.p === p.id);
    const msgsP = sum(L, (s) => s.msgs) + (p.id === 'confluo' ? 7 : 0);
    const target = Math.max(0, Math.round(msgsP * p.fr / 100 * 1.1) - (p.id === 'confluo' ? 2 : 0));
    const v = largestRemainder(L.map((s) => s.lam + 0.05), target);
    L.forEach((s, i) => { s.corr = v[i]; });
  });
  const all = out.concat(sep);
  const cnt = {};
  all.forEach((s) => {
    const P = PJI[s.p];
    const rr = rng(hash(s.p + s.d + ':' + s.h + ':' + s.mi + s.a));
    const er = s.errors / Math.max(1, s.tools);
    s.out = ((s.corr >= 2 && rr() < 0.35) || rr() < 0.02) ? 'fail' : ((er > 0.09 && rr() < 0.4) || (s.corr >= 1 && rr() < 0.1)) ? 'part' : 'ok';
    s.verify = rr() < (P.V / 100) * 0.92;
    s.mood = clamp(0.38 - s.corr * 0.22 - (s.out === 'fail' ? 0.45 : s.out === 'part' ? 0.18 : 0) - (s.errors / Math.max(1, s.tools)) * 0.8 + (s.verify ? 0.05 : 0) + (rr() - 0.5) * 0.25, -1, 1);
    s.topic = pickW(rr, P.topics);
    s.fric = s.corr > 0 ? pickW(rr, P.fric) : null;
    cnt[s.p] = (cnt[s.p] || 0) + 1;
    const n = cnt[s.p] - 1;
    s.title = P.titles[n % P.titles.length] + ['', '（续）', ' · 收尾', ' · 返工', ' · 复盘'][Math.floor(n / P.titles.length) % 5];
  });
  all.push(FEAT);
  all.push({ id: 'sess-1001-1512', d: 120, a: 'cc', p: 'hackathon', h: 15, mi: 12, dur: 18.7, msgs: 4, tools: 61, errors: 1, corr: 0, out: 'live', live: true, verify: true, mood: 0.3, topic: 'design', title: '设计 Orbit Mac App 视觉案例' });
  all.push({ id: 'sess-1001-0903', d: 120, a: 'cx', p: 'teamhub', h: 9, mi: 3, dur: 12, msgs: 3, tools: 34, errors: 0, corr: 0, out: 'ok', verify: true, mood: 0.35, topic: 'git', title: '同步 team-hub collab 并审核日报' });
  all.sort((x, y) => (x.d - y.d) || (x.h - y.h) || (x.mi - y.mi));
  all.forEach((s, i) => {
    const x = dayDate(s.d);
    if (!s.id) s.id = 'sess-' + String(x.getUTCMonth() + 1).padStart(2, '0') + String(x.getUTCDate()).padStart(2, '0') + '-' + hm(s.h, s.mi).replace(':', '') + '-' + i;
    s.tok = Math.round(s.tools * (11 + (hash(s.id) & 7)) * 1000 + s.msgs * 4000);
    delete s.lam;
  });
  demoLean(all);
  demoUnits(all);
  return all;
}
// 示例会话的四维倾向（只供画像页表盘把每个会话归到它偏向的类型，不参与其它任何统计）：按会话 id 的哈希单独取随机数，
// 不动 genSessions 的随机序列，其它页面的数字不变。类型权重让外圈有六个分开、宽窄高低不一的峰，四周大致均匀：DIMV（你的类型，
// 最高，带 DIMT 一点肩）在 12 点右侧，DIFV + DPFV 一座宽峰在委托，DPMT 在右下，SPMV + SPMT 一座宽峰在规划左侧，SIFV 在掌舵，
// SIMT 一座小峰在左上；峰之间的类型只有零星会话，谷底贴近基线。各 Agent 偏向其中一个峰（Claude Code 偏 DIMV、Codex 偏委托求证、
// DeepSeek 偏规划多线、OpenCode 偏规划掌舵、Kimi 偏即兴掌舵），徽章因此散在四周，每个峰里色带的占比也不同。live 会话不带这个字段。
const LEAN_W = { DIMV: 6.5, DIMT: 1.4, DIFT: 0.2, DIFV: 2.4, DPFV: 2, DPFT: 0.2, DPMT: 1.6, DPMV: 0.2, SPMV: 1.8, SPMT: 2.2, SPFT: 0.2, SPFV: 0.2, SIFV: 4, SIFT: 0.2, SIMT: 1.6, SIMV: 0.2 };
const LEAN_AG = { cc: { DIMV: 1.5 }, cx: { DIFV: 5 }, ds: { DPMT: 20 }, oc: { SPMT: 30 }, km: { SIFV: 12 } };
function demoLean(all) {
  all.forEach((s) => {
    const r = rng(hash(s.id + ':lean')), tilt = LEAN_AG[s.a] || {}, w = {};
    for (const k in LEAN_W) w[k] = LEAN_W[k] * (tilt[k] || 1);
    const code = pickW(r, w), v = {};
    ['D', 'I', 'M', 'V'].forEach((k, i) => { const x = 60 + r() * 32; v[k] = Math.round(code[i] === k ? x : 100 - x); });
    s.lean = v;
  });
}
// 示例会话的人格单位（与 live 线上行同名：dk/dn/vk/ik/kn/ol/oa/os/sc/rb/t0/t1），供 persona() 的多信号口径使用。
// 按会话 id 的哈希单独取随机数，不动 genSessions 的随机序列；由会话已有的字段推出：人类轮次 = 消息数，≥ 5 步的轮次占比随
// 每条消息的工具调用数上升，验证轮次只出现在 verify 会话里，开场结构 / 规格引用随项目的即兴倾向（I），回滚多见于需返工的会话。
function demoUnits(all) {
  // only Claude Code and Codex record child sessions (facts.SUBAGENT_AGENTS); for the others the signal is unknown (null)
  const AGSUB = { cc: 0.3, cx: 0.12 };
  all.forEach((s) => {
    const r = rng(hash(s.id + ':units')), P = PJI[s.p] || { I: 60, V: 50 };
    const dn = Math.max(1, s.msgs), per = s.tools / Math.max(1, s.msgs);
    const fd = clamp((per - 1.5) / 7, 0.1, 0.95);
    let dk = 0, vk = 0, ik = 0;
    for (let i = 0; i < dn; i++) {
      if (r() < fd) dk++;
      if (s.verify && r() < 0.92) vk++;
      if (r() < 0.02 + (s.msgs ? s.corr / s.msgs : 0) * 0.25) ik++;
    }
    if (s.verify && !vk) vk = 1;
    const planned = r() > P.I / 100;
    s.dk = dk; s.dn = dn; s.vk = vk; s.ik = ik; s.kn = dn;
    s.oa = planned ? 1 : 0; s.os = planned && r() < 0.35 ? 1 : 0;
    s.ol = Math.round(planned ? 160 + r() * 420 : 18 + r() * 110);
    const sc = r() < (AGSUB[s.a] || 0.05) ? 2 + Math.floor(r() * 3) : r() < 0.2 ? 1 : 0;
    s.sc = AGSUB[s.a] ? sc : null;
    s.rb = r() < 0.12 + (s.out === 'part' || s.out === 'fail' ? 0.35 : 0) ? 1 : 0;
    s.t0 = ((s.d * 24 + s.h) * 60 + s.mi) * 60000; s.t1 = s.t0 + Math.round(s.dur * 60000);
  });
}
const ALL = genSessions();
const BYID = {}; ALL.forEach((s) => { BYID[s.id] = s; });

const TOOLS = [
  ['Bash', 4212, 0.112, '4.2 s', 0.224, ['git status', 'npm run build', 'pytest -q', 'npx wrangler pages deploy ./dist', 'gh pr view 12', 'latexmk -pdf main.tex']],
  ['Read', 1980, 0.012, '0.1 s', 0, ['Read src/components/Card.tsx', 'Read docs/plan/v2/07.md', 'Read paper/sec3.tex']],
  ['Edit', 1406, 0.034, '0.2 s', 0.04, ['Edit src/deck.ts', 'Edit AGENTS.md', 'Edit paper/sec3.tex']],
  ['Grep', 802, 0.006, '0.3 s', 0, ['Grep "wrangler"', 'Grep "TODO"', 'Grep "cite{"']],
  ['Task', 516, 0.041, '96 s', 0, ['Task Explore ×3', 'Task 引用核查', 'Task 规则审计']],
  ['WebFetch', 288, 0.125, '2.8 s', 0.33, ['WebFetch https://confluo…', 'WebFetch arxiv.org/abs/…']],
  ['Write', 240, 0.008, '0.1 s', 0.09, ['Write notes/summary.md', 'Write scripts/check.sh']],
  ['Glob', 196, 0, '0.1 s', 0, ['Glob **/*.tex', 'Glob src/**/*.ts']],
  ['TodoWrite', 120, 0, '0.0 s', 0, ['TodoWrite 5 项']],
  ['mcp·browser', 64, 0.078, '3.6 s', 0.41, ['browser.screenshot', 'browser.navigate']],
  ['WebSearch', 36, 0.028, '1.9 s', 0, ['WebSearch "wrangler pages custom domain"']]
];
const TRANS_NAMES = ['Read', 'Grep', 'Edit', 'Bash', 'Task', 'Web'];
const TRANS = [[0.22, 0.08, 0.41, 0.17, 0.04, 0.03], [0.58, 0.14, 0.12, 0.10, 0.02, 0.02], [0.18, 0.06, 0.34, 0.33, 0.03, 0.02], [0.17, 0.07, 0.21, 0.31, 0.05, 0.06], [0.32, 0.09, 0.26, 0.21, 0.08, 0.02], [0.21, 0.04, 0.15, 0.26, 0.03, 0.27]];
const FAILS = [['环境 / 命令不存在', 31, 'wrangler: command not found（×37）'], ['权限被拒', 22, 'EACCES: permission denied, open ~/.ssh/config'], ['超时', 14, 'WebFetch 超时 120 s'], ['网络', 12, 'curl: (6) Could not resolve host'], ['参数 / 语法', 11, 'error: unknown option --prod'], ['其他', 10, 'exit 1（无输出）']];
const WAITS = [['<5s', 214], ['5–15s', 268], ['15–30s', 205], ['30–60s', 182], ['1–2m', 131], ['2–5m', 96], ['>5m', 46]];

/* recommendations: dims rule | skill | hook | mcp | agent | model | flow */
const DIMS = [['all', '全部'], ['rule', '规则与 Prompt'], ['skill', 'Skills'], ['hook', 'Hooks'], ['mcp', '插件 / MCP'], ['agent', '子代理'], ['model', '模型与思考'], ['flow', '工作流 / 架构']];
const LEVELS = ['', 'L1 一键', 'L2 复制粘贴', 'L3 需配置', 'L4 架构调整'];
const AUD = ['新手', '进阶', '专家'];
const RECS = [
  { id: 'ro-allow', dim: 'hook', type: 'Hook', icon: 'bolt', lvl: 1, aud: 0, title: '只读命令自动放行', gain: '−212 次审批 / 月', why: '你手动批准了 212 次 git status、ls、gh pr view 这类只读命令。', ev: '38 个会话', evq: { tool: 'Bash' }, compat: 'Claude Code · Codex', c2: 'var(--a2)', primary: '一键应用', target: '~/.claude/settings.json',
    file: [['{', ' '], ['  "permissions": {', ' '], ['    "allow": [', ' '], ['      "Bash(git status:*)",', '+'], ['      "Bash(git diff:*)",', '+'], ['      "Bash(git log:*)",', '+'], ['      "Bash(ls:*)",', '+'], ['      "Bash(gh pr view:*)",', '+'], ['      "Bash(gh pr checks:*)",', '+'], ['      "Read(~/Projects/**)"', ' '], ['    ]', ' '], ['  }', ' '], ['}', ' ']],
    steps: ['点「预览」查看将写入 settings.json 的 6 条放行规则', '确认写入（会先备份原文件）', '新开一个会话运行 git status，确认不再弹出审批', '7 天后在「效果追踪」里看审批次数变化'], track: [['每周审批次数', 53, 9, '次'], ['平均等待时间', 38, 31, 's'], ['相关会话摩擦率', 9.1, 7.4, '%']] },
  { id: 'pr-wrapup', dim: 'skill', type: 'Skill', icon: 'book', lvl: 2, aud: 1, title: 'PR 收尾：最多两轮 review，只修 P0 / P1', gain: 'review 轮次 −60%', why: 'review 循环中位 4 轮、最长 11 轮，有 6 次以「直接合并」收场。', ev: '46 个会话', evq: { topic: 'git' }, compat: 'Claude Code · 转换给 Codex', c2: 'var(--a2)', primary: '预览并安装', target: '~/.claude/skills/pr-wrapup/SKILL.md',
    file: [['---', ' '], ['name: pr-wrapup', '+'], ['description: 合并前收尾。触发 review，只修 P0/P1，', '+'], ['  最多两轮，之后合并并删除分支', '+'], ['---', ' '], ['# PR 收尾', '+'], ['1. 确认 CI 通过，review 汇总为 Completed', '+'], ['2. 只处理 P0 / P1；其余逐条回复理由', '+'], ['3. 第二轮后仍有意见：停止并向我汇报', 'ai'], ['4. 合并方式沿用仓库约定（merge commit）', '+'], ['5. 合并后删除远端与本地分支', '+'], ['', ' '], ['## 不要做', '+'], ['- 不要为 P2 意见开启新一轮 review', '+']],
    steps: ['预览 SKILL.md（已按你的仓库约定改写 6 处）', '选择安装范围：全局或仅当前项目', '在下一个 PR 里说「按 pr-wrapup 收尾」', '7 天后对比 review 轮次'], track: [['平均 review 轮次', 4.1, 1.6, '轮'], ['合并耗时中位数', 96, 41, '分钟'], ['「直接合并」类纠偏', 6, 1, '次']] },
  { id: 'deploy-target', dim: 'rule', type: '规则', icon: 'rule', lvl: 1, aud: 0, title: 'AGENTS.md：写明部署目标与禁用平台', gain: '覆盖 4 类方向偏离', why: '4 次部署被引向 Vercel，而你的项目约定是 Cloudflare。', ev: '4 个会话', evq: { fric: '方向错误' }, compat: '所有 Agent', c2: 'var(--a3)', primary: '复制片段', target: 'Confluo/AGENTS.md',
    file: [['## 部署', '+'], ['- 部署目标：Cloudflare Pages（wrangler）', '+'], ['- 不要使用 Vercel、Netlify 或其他平台', '+'], ['- 部署前先运行 npx wrangler whoami，未登录就停下来告诉我', 'ai'], ['- 部署后验证：线上 200、HTTPS、www 跳转', '+']],
    steps: ['复制片段', '粘贴到项目根目录的 AGENTS.md「部署」小节', '下次部署时观察 Agent 是否先检查登录状态'], track: [['部署方向偏离', 4, 0, '次'], ['部署会话平均时长', 47, 33, '分钟'], ['部署类会话摩擦率', 12.4, 6.2, '%']] },
  { id: 'think-medium', dim: 'model', type: '模型与思考', icon: 'gauge', lvl: 1, aud: 1, title: '只读审查任务改用 thinking medium', gain: '−28% tokens', why: '审阅类会话中思考 token 占 61%，medium 与 high 的结论一致率为 94%。', ev: '22 个会话', evq: { project: 'latentskill' }, compat: 'Claude Code', c2: 'var(--a1)', primary: '应用到 latentskill', target: 'latentskill · Orbit 任务预设',
    file: [['# latentskill · 审查类任务预设', ' '], ['match: 只读审查（以 Read / Grep 为主，没有 Edit）', '+'], ['thinking: medium', '+'], ['fallback: high（出现 Edit 时自动恢复）', 'ai']],
    steps: ['应用预设到 latentskill', '审查类会话开始时 Orbit 会提示建议档位', '7 天后对比 token 与结论一致率'], track: [['审查会话 tokens', 410, 296, 'k'], ['结论一致率', 100, 94, '%'], ['平均耗时', 21, 16, '分钟']] },
  { id: 'retry-breaker', dim: 'hook', type: 'Hook', icon: 'bolt', lvl: 2, aud: 1, title: '重复失败熔断：同一命令失败 2 次先诊断', gain: '重复失败 −68%', why: '有 23 段「失败后原样重试」的序列，最长一次连续 4 次。', ev: '17 个会话', evq: { fric: '工具 / 环境失败' }, compat: 'Claude Code · Codex', c2: 'var(--a2)', primary: '预览并安装', target: '~/.claude/settings.json',
    file: [['{', ' '], ['  "hooks": {', '+'], ['    "PostToolUse": [', '+'], ['      {', '+'], ['        "matcher": "Bash",', '+'], ['        "hooks": [', '+'], ['          { "type": "command",', '+'], ['            "command": "~/.orbit/hooks/retry-breaker.sh" }', 'ai'], ['        ]', '+'], ['      }', '+'], ['    ]', '+'], ['  }', '+'], ['}', ' ']],
    steps: ['预览将写入的 Hook 与脚本', '确认安装（脚本放在 ~/.orbit/hooks，可随时删除）', '下次出现连续失败时，Agent 会先停下来检查认证与环境'], track: [['重复失败序列', 23, 7, '段'], ['失败后浪费时长', 58, 17, '分钟'], ['工具类摩擦', 12, 5, '次']] },
  { id: 'worktree', dim: 'flow', type: '工作流', icon: 'branch', lvl: 3, aud: 1, title: '并行会话改用 git worktree 隔离', gain: '并行冲突 −5 次 / 月', why: '多个会话同时改同一仓库，产生了 5 次冲突与 2 次覆盖。', ev: '9 个会话', evq: { fric: '并行会话冲突' }, compat: 'Claude Code · Codex', c2: 'var(--a2)', primary: '查看教程', target: '教程（不写入文件）',
    file: [['# 为每个并行会话建立独立 worktree', ' '], ['git worktree add ../Hackathon-a feat/a', '+'], ['git worktree add ../Hackathon-b feat/b', '+'], ['# 在各自目录里启动 Agent，结束后：', ' '], ['git worktree remove ../Hackathon-a', '+']],
    steps: ['为每个要并行的任务建一个 worktree', '在各自目录启动 Agent', '完成后在主目录合并并清理 worktree', '也可以交给生成工坊做成一个 Skill'], track: [['并行冲突', 5, 0, '次'], ['覆盖他人改动', 2, 0, '次'], ['并行会话数', 41, 44, '次']] },
  { id: 'citation-checker', dim: 'agent', type: '子代理', icon: 'bot', lvl: 2, aud: 1, title: '引用核查子代理（citation-checker）', gain: '引用返工 −3 次 / 月', why: '论文会话里 9 次纠偏与引用格式和 BibTeX 有关。', ev: '9 个会话', evq: { project: 'latentskill' }, compat: 'Claude Code · Kimi CLI', c2: 'var(--a3)', primary: '预览并安装', target: '~/.claude/agents/citation-checker.md',
    file: [['---', ' '], ['name: citation-checker', '+'], ['description: 核对 \\cite 与 BibTeX 的一致性，输出问题表', '+'], ['tools: Read, Grep', '+'], ['---', ' '], ['只读。逐条检查正文引用是否都在 .bib 中、键名是否一致、', '+'], ['年份与作者是否与原文相符；结果用表格列出，不要改文件。', 'ai']],
    steps: ['预览子代理定义', '安装到 ~/.claude/agents', '在论文会话中说「请 citation-checker 检查第 3 节」'], track: [['引用类纠偏', 9, 3, '次'], ['审稿会话时长', 66, 52, '分钟'], ['BibTeX 错误', 14, 2, '处']] },
  { id: 'remove-figma', dim: 'mcp', type: 'MCP', icon: 'puzzle', lvl: 1, aud: 0, title: '移除闲置的 figma MCP', gain: '每个会话省 ≈ 2.1k tokens', why: 'figma MCP 已安装 41 天，从未被调用，却一直占用上下文。', ev: '186 个会话', evq: {}, compat: 'Claude Code', c2: 'var(--a1)', primary: '一键移除', target: '~/.claude.json · mcpServers',
    file: [['"mcpServers": {', ' '], ['  "browser": { … },', ' '], ['  "figma": { "command": "figma-mcp", "args": [] }', '-'], ['}', ' ']],
    steps: ['预览要删除的配置项', '确认移除（会备份）', '需要时可在资源库重新安装'], track: [['每会话常驻 tokens', 2100, 0, ''], ['会话启动时长', 3.1, 2.6, 's'], ['MCP 数量', 2, 1, '个']] },
  { id: 'acceptance', dim: 'rule', type: 'Prompt', icon: 'rule', lvl: 1, aud: 0, title: '开场模板：先写完成条件', gain: '纠偏 −30%（同类用户）', why: '只有 23% 的首条消息写明了完成条件；写明时你的纠偏少 30%。', ev: '43 个会话', evq: {}, compat: '所有 Agent', c2: 'var(--a3)', primary: '复制模板', target: '剪贴板 / AGENTS.md',
    file: [['目标：', '+'], ['完成条件：（怎样算做完，可验证）', 'ai'], ['不要做：', '+'], ['验证方式：（测试 / 编译 / 线上检查）', '+']],
    steps: ['复制模板', '开新任务时先填四行', '也可以写进 AGENTS.md，让 Agent 在你没写时主动追问'], track: [['写明完成条件的比例', 23, 58, '%'], ['平均纠偏次数', 0.6, 0.4, '次'], ['首轮完成率', 61, 72, '%']] },
  { id: 'latex-hook', dim: 'hook', type: 'Hook', icon: 'bolt', lvl: 2, aud: 1, title: '改动 .tex 后自动编译并检查页数', gain: '页数返工 −2 次 / 月', why: '有 5 个会话在最后才发现超出 9 页，回头再压缩。', ev: '5 个会话', evq: { project: 'latentskill' }, compat: 'Claude Code', c2: 'var(--a1)', primary: '预览并安装', target: 'latentskill/.claude/settings.json',
    file: [['"hooks": {', '+'], ['  "PostToolUse": [{', '+'], ['    "matcher": "Edit|Write",', '+'], ['    "hooks": [{ "type": "command",', '+'], ['      "command": "latexmk -pdf -silent main.tex && pdfinfo main.pdf | grep Pages" }]', 'ai'], ['  }]', '+'], ['}', '+']],
    steps: ['预览 Hook', '只安装到 latentskill 项目', '改动 .tex 后会自动编译并报告页数'], track: [['超页返工', 5, 1, '次'], ['编译失败未发现', 3, 0, '次'], ['审稿会话时长', 66, 58, '分钟']] },
  { id: 'summary-compact', dim: 'rule', type: '规则', icon: 'rule', lvl: 1, aud: 0, title: '上下文过 60% 先总结再继续', gain: '压缩后返工 −40%', why: '9 次自动压缩后，Agent 丢失了之前的约定，你需要重复说明。', ev: '9 个会话', evq: {}, compat: '所有 Agent', c2: 'var(--a3)', primary: '复制片段', target: 'AGENTS.md',
    file: [['## 长会话', '+'], ['- 上下文用量超过 60% 时，先用 10 行总结：目标、已做、决定、待办', 'ai'], ['- 总结后再继续；不要等到自动压缩', '+']],
    steps: ['复制片段', '粘贴到全局 AGENTS.md', '悬浮组件会在 60% 时提醒你'], track: [['压缩后重复说明', 9, 5, '次'], ['长会话摩擦率', 11.2, 8.1, '%'], ['自动压缩次数', 14, 8, '次']] },
  { id: 'paper-audit', dim: 'skill', type: 'Skill', icon: 'book', lvl: 2, aud: 1, title: '审稿流程 Skill：只读审查 → 归档 → 最小修改', gain: '每次审稿少说约 4 条指令', why: '你在 19 个论文会话里重复了同一套五步流程。', ev: '19 个会话', evq: { project: 'latentskill' }, compat: 'Claude Code', c2: 'var(--a1)', primary: '交给 Agent 生成', target: '~/.claude/skills/paper-audit/SKILL.md',
    file: [['---', ' '], ['name: paper-audit', '+'], ['description: 论文审阅的固定流程：只读审查、归档、最小修改、编译、页数检查', '+'], ['---', ' '], ['1. 只读审查，先列问题，不改文件', '+'], ['2. 修改前把当前版本复制到 archive/', '+'], ['3. 每次只做最小修改，并说明理由', '+'], ['4. latexmk 编译；正文不超过 9 页', 'ai']],
    steps: ['交给生成工坊，用你的 19 个会话生成定制版', '审阅并安装', '下次审稿时说「按 paper-audit」'], track: [['每次审稿的指令数', 9, 5, '条'], ['审稿会话时长', 66, 49, '分钟'], ['改动过度类纠偏', 4, 1, '次']] },
  { id: 'headless', dim: 'flow', type: '工作流', icon: 'clock', lvl: 4, aud: 2, title: '长时间采集改为 headless + 定时检查', gain: '人工查看进度 −15 次 / 周', why: '轨迹采集期间你平均每 40 分钟手动问一次进度。', ev: '8 个会话', evq: { project: 'latentskill' }, compat: 'Claude Code · DeepSeek', c2: 'var(--a4)', primary: '查看教程', target: '教程（需要 cron 与脚本）',
    file: [['# 每 30 分钟检查一次采集进度', ' '], ['*/30 * * * * claude -p "检查 runs/ 的进度，异常时总结原因" >> ~/logs/collect.log', '+']],
    steps: ['确认采集脚本能无人值守运行', '配置 cron 或 launchd 定时任务', '异常时由 Orbit 发通知'], track: [['手动查看进度', 15, 2, '次 / 周'], ['异常发现延迟', 95, 30, '分钟'], ['采集中断', 3, 1, '次']] }
];
const RECI = {}; RECS.forEach((r) => { RECI[r.id] = r; });

const LIB = [
  { id: 'worktree-conductor', kind: 'Skill', icon: 'branch', src: '社区 · MIT', desc: '为每个并行会话自动建立独立 worktree，结束后合并并清理。', m: 94, sc: [96, 92, 74], why: ['你每周约 10 次并行会话，5 次改到同一仓库', '同为 DIMV 的用户安装后冲突减少 72%'], compat: 'Claude Code · Codex', users: 3100, peer: 68, rec: 'worktree' },
  { id: 'retry-breaker', kind: 'Hook', icon: 'bolt', src: 'Orbit 官方', desc: '同一命令失败 2 次后暂停，先诊断认证与环境再继续。', m: 89, sc: [88, 95, 81], why: ['23 段「失败后原样重试」，最长 4 次', '覆盖你第二大的摩擦：工具 / 环境失败'], compat: 'Claude Code · Codex', users: 1800, peer: 52, rec: 'retry-breaker' },
  { id: 'release-verifier', kind: '子代理', icon: 'bot', src: '社区 · Apache-2.0', desc: '部署完成后独立检查线上状态码、HTTPS、跳转与缓存。', m: 86, sc: [90, 84, 79], why: ['61% 的会话你会要求验证线上结果', '可以把验收从主会话中拆出去'], compat: 'Claude Code · Kimi CLI', users: 940, peer: 43, rec: 'deploy-target' },
  { id: 'paper-audit-loop', kind: 'Skill', icon: 'book', src: '本地生成', local: true, desc: '只读审查 → 归档 → 最小修改 → 编译 → 页数检查。', m: 84, sc: [86, 88, 70], why: ['你在 19 个会话里重复这五步', '由你的本地 Agent 依据你的会话生成'], compat: 'Claude Code', users: 0, peer: 0, rec: 'paper-audit' },
  { id: 'cloudflare-deploy', kind: '插件', icon: 'plug', src: '社区 · MIT', desc: 'wrangler 登录检查、Pages 部署与域名验证命令集。', m: 81, sc: [78, 90, 72], why: ['部署类会话里 4 次走错平台', 'wrangler 未登录导致 37 次失败'], compat: 'Claude Code · Codex', users: 5600, peer: 39, rec: 'deploy-target' },
  { id: 'readonly-allowlist', kind: 'Hook', icon: 'bolt', src: 'Orbit 官方', desc: '把 git status、ls、gh pr view 等只读命令加入白名单。', m: 79, sc: [74, 92, 70], why: ['212 次只读命令需要你手动批准', '审批平均等待 38 秒'], compat: 'Claude Code · Codex', users: 12000, peer: 61, rec: 'ro-allow' },
  { id: 'gh-review-digest', kind: 'MCP', icon: 'puzzle', src: '社区 · MIT', desc: '把多轮 review 意见合并成一份按优先级排序的清单。', m: 74, sc: [70, 82, 66], why: ['review 循环最长 11 轮', '与 PR 收尾 Skill 搭配效果最好'], compat: 'Claude Code', users: 2200, peer: 27, rec: 'pr-wrapup' },
  { id: 'citation-checker', kind: '子代理', icon: 'bot', src: '社区 · MIT', desc: '核对论文引用与 BibTeX，一致性问题列成表。', m: 71, sc: [64, 86, 60], why: ['9 次纠偏与引用格式有关', '只读，不会改你的文件'], compat: 'Claude Code · Kimi CLI', users: 780, peer: 18, rec: 'citation-checker' },
  { id: 'bilingual-report', kind: 'Skill', icon: 'book', src: '社区 · CC BY', desc: '英文交付后自动附中文版，术语表保持一致。', m: 66, sc: [72, 58, 64], why: ['你常在英文结果后要求翻译', '中英混用占 7%'], compat: '所有 Agent', users: 1100, peer: 22, rec: 'acceptance' },
  { id: 'context-saver', kind: 'Hook', icon: 'bolt', src: 'Orbit 官方', desc: '上下文超过 60% 时提醒先总结，再继续。', m: 63, sc: [60, 70, 58], why: ['9 次压缩后需要重复说明约定', '长会话摩擦率 11.2%'], compat: 'Claude Code', users: 4300, peer: 31, rec: 'summary-compact' },
  { id: 'commit-coach', kind: 'Skill', icon: 'book', src: '社区 · MIT', desc: '按约定格式写提交信息，并提醒小步提交。', m: 58, sc: [62, 50, 61], why: ['你的仓库要求 type(scope): 描述', '小步提交时你的满意度更高'], compat: '所有 Agent', users: 6800, peer: 47, rec: 'acceptance' },
  { id: 'headless-scheduler', kind: '插件', icon: 'clock', src: '社区 · MIT', desc: '把长任务改成 headless 运行，定时汇报进度。', m: 55, sc: [52, 64, 48], why: ['采集任务期间频繁手动查看进度', '适合专家用户'], compat: 'Claude Code', users: 900, peer: 12, rec: 'headless' }
];

const PHRASES = [['用中文', 9, '偏好'], ['直接合并', 6, '纠偏'], ['先只读审查', 5, '规划'], ['部署后验证线上', 7, '验证'], ['简洁一点', 4, '风格'], ['别用子代理', 3, '纠偏'], ['不要改别的文件', 4, '纠偏'], ['用 Cloudflare 不是 Vercel', 2, '纠偏']];
// A6 高频词 (demo): [词, 近 30 天次数, 出现天数] for the 186-session demo month; the page scales them with the filters
const WORDS = [['合并', 64, 26], ['提交', 58, 27], ['测试', 55, 25], ['部署', 49, 21], ['继续', 47, 28], ['验证', 44, 22], ['review', 40, 18], ['页面', 37, 16], ['规则', 35, 19], ['修复', 33, 20], ['论文', 30, 11], ['中文', 29, 24], ['接口', 27, 13], ['数据', 26, 15], ['分支', 25, 17], ['推送', 24, 18], ['截图', 22, 12], ['配置', 21, 14], ['文档', 20, 13], ['子代理', 18, 10], ['cloudflare', 17, 8], ['简洁', 16, 12], ['只读', 15, 11], ['样式', 15, 9], ['动画', 14, 7], ['侧栏', 14, 6], ['日志', 13, 9], ['脚本', 12, 8], ['回滚', 12, 7], ['模型', 11, 8], ['latex', 11, 5], ['引用', 10, 5], ['审查', 10, 8], ['性能', 9, 6], ['权限', 9, 7], ['上下文', 9, 6], ['采集', 8, 5], ['回测', 8, 4], ['图表', 7, 5], ['缓存', 7, 5], ['依赖', 6, 5], ['字体', 6, 3], ['端口', 6, 4], ['代理规则', 5, 3], ['清单', 5, 4], ['发布', 5, 4], ['翻译', 5, 4], ['进度', 5, 5], ['重构', 4, 3], ['工作流', 4, 3], ['wrangler', 4, 2], ['快捷键', 4, 2], ['对比', 4, 3], ['导出', 3, 3], ['告警', 3, 2], ['周报', 3, 3], ['排期', 3, 2], ['词云', 3, 1], ['备份', 2, 2], ['水印', 2, 1]];
const DRIVERS = [['会话超过 90 分钟', -0.31], ['同一命令连续失败 ≥ 2 次', -0.44], ['首条消息写明完成条件', 0.27], ['小步提交并推送', 0.19]];
const QUOTES = { pos: ['「可以，这版很好，直接合并」', '「线上验证过了，谢谢」', '「对，就是这个意思」', '「这个思路好，继续」'], neg: ['「不要用 Vercel，用 Cloudflare」', '「别再跑 review 了，直接合并」', '「先停一下，你改太多了」', '「为什么又中断了」', '「不是这个意思」'], mid: ['「继续」', '「先看看现在的进度」', '「好的，下一步」'] };

