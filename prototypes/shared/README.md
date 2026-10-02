# 共享 live 适配层（TandemLive）

Lite 与 Advance 共用的前端数据适配层。权威源是 `tandem-live.js`（无依赖浏览器脚本，也可被 Node `require`），两份副本由 `sync-live.mjs` 生成：

| 副本 | 位置 |
| --- | --- |
| Advance | `prototypes/advance/src/js/06-live-client.js`（生成文件，带头注释），构建进 `tandem-demo.html` |
| Lite | `prototypes/lite/tandem-benchmark-demo.html` 中 `@tandem-live:generated begin / end` 标记之间 |

修改适配层后依次运行：

```bash
node prototypes/shared/sync-live.mjs          # 更新两处副本
node prototypes/advance/build.mjs             # 重新生成 tandem-demo.html
pnpm --filter @tandem/prototype-lite check    # benchmark 检查 + sync --check + node --test
```

## 模式

- **mock**（默认）：`file://` 或独立打开。适配层不发请求、不改页面，Demo 的视觉与行为不变。
- **live**：由 gateway 提供的 `/app`、`/lite`，或带 `?live=1`。端点取 `window.__TANDEM_ENDPOINT__`（缺省为当前 origin），令牌取 `window.__TANDEM_TOKEN__`，开发期可用 `#token=…`（读取后从地址栏移除）。gateway 重启后派发 `tandem:endpoint` 事件（`detail: {endpoint, token}`）即可重连。
- live 一旦建立，失败时显示错误并保留上一屏数据，**不回退成演示数据**。

## 能力

- `get(path, {scope, waitMs, signal})`：带 `If-None-Match`，`304` 复用缓存；同键并发合并；页面切换时用 `AbortController` 取消上一页请求。
- Scope 序列化：重复 query 参数；显式空值 `key=` 表示零个；时间预设换算为本地日起点的 `from_ts`，不传 `until_ts`；Agent id 经 `/v1/status` 的 `sources` 映射为 `source_ids`（停用来源不计入）。
- 资源八态：`idle / loading / ready / stale / computing / empty / error / importing`，保留 last-good；`202 computing` 显示骨架并在 `analysis.ready` 后重取；`503` 按 `Retry-After` 重试。
- `/v1/events`：用 `fetch` 读取 SSE 文本帧（带 `Authorization`），指数退避重连，`Last-Event-ID` 续传，帧号缺口时 resync；事件只失效对应资源并触发 `render()`。
- `bind(page, resources, toViewModel)` / `view(page, scope)`：把 API 响应转成页面渲染形状；`ui.*` 提供进度条、横幅、陈旧 / 计算中徽标、“示例数据”徽标、空态与 `null → —` 格式化。

页面绑定分别在 `prototypes/advance/src/js/96-live-bind.js` 与 Lite 的 `@tandem-live block` 中，目前绑定概览、会话与事件、工具、项目、侧栏计数与 Agents、设置 › 数据源；其余页面在 live 下显示“示例数据”徽标。

## 测试

- `tests/`：`node --test`，覆盖 ETag/304、合并与取消、陈旧→刷新、202→`analysis.ready`、503 保留上一屏、SSE 重连 / 续传 / resync、live 失败不回退、示例数据徽标、Scope 序列化。
- `prototypes/advance/tests/live-adapter.spec.mjs`：Playwright 用 `page.route` 模拟 gateway，覆盖 mock 不变与 live 各页面。
- `fixtures/*.json`：手写合成夹具（含 `meta`、`202 computing`、`stale`、`503`、空态），不依赖后端实现，也不含真实会话。

## 优化建议（recs 段）

- 适配层 `tandem-live.js` 的 recs 段：`TandemLive.recs.row(cand)` 把 `/v1/recommendations` 的 `Cand.ui` 映射为原型 `RECS` 行（节省时间由 `score.benefit` 折算，缺失为 `null` →「—」）；`C.recs` 提供 `desc / resource(surface)`、`detail`、`relations`、`exposure`、`viewed`（按 surface 去重的批量 view）、`label / unlabel`、`recompute`、`invalidate`。
- Advance：`src/js/97-live-recs.js` 在 live 下替换 `RECS / RECI / REC_X`，沿用 A7、A1「本周建议」、Lite 首页与 l-recs、菜单栏的原渲染器；`recOrder / recTop(surface)` 把后端 A1 / lite / menubar 稳定置顶排在前面。不适用（含原因）/ 稍后 / 不再推荐同类写 label，8 秒内可撤销。
- Lite 单文件：`@tandem-live recs block` 绑定「优化建议」页。
- 降级：从未取得 live 数据且端点 404 / 501 / 503 / 离线时保留演示数据并标「示例数据」；取得过 live 数据后失败只保留上一屏。
- 夹具：`fixtures/recs/*.json`（每个端点一份，合成数据）；单测 `tests/tandem-live-recs.test.cjs`。
