# OrbitLive 共享适配层

`orbit-live.js` 是共享浏览器客户端，也可由 Node 测试。`sync-live.mjs` 将它同步到 Advance 的生成副本和 Lite 原稿标记区；修改源文件后再同步，避免两份实现分叉。

```sh
node prototypes/shared/sync-live.mjs
pnpm --filter @orbit/prototype-advance build
pnpm --filter @orbit/prototype-lite check
```

## 模式和鉴权

独立 HTML 默认 mock，不读取个人记录。gateway 页面或显式 live 模式使用注入的 endpoint/token；开发可通过 fragment 提供 token，读取后移除。宿主重启经 `orbit:endpoint` 更新连接。

真实页面从空骨架或已取得的真实结果开始。请求失败时显示明确状态并保留 last-good，不能用个人 Demo 数据填充 live 空态；显式开发演示模式仍需标注。

## 请求与状态

- `get` 管理 Scope、ETag/304、同键合并和取消。
- Scope 保留重复参数及显式空选择，时间按显示时区转换；来源映射通过服务状态核对。
- 资源区分 idle、loading、ready、stale、computing、empty、error、importing；202/503 不是有效空结果。
- SSE 带授权，支持事件游标、重连与失效通知；检测缺口时重新同步。
- `bind/view` 负责页面模型，格式化保留 null、覆盖、新鲜度和示例标记。

## 页面绑定

Advance 的 `90-live-core.js` 至 `98-live-ops.js` 分别接入公共状态、各分析页、推荐、AI、安装、实时组件与导出。`C.recs` 管推荐、关系和反馈，`C.ops` 管会话操作、实时快照和导出；路由和字段以当前绑定及 gateway 为准。

适配层不拥有统计口径。百分比、类型、安装状态与覆盖由对应后端合同提供，UI 不另补造分母或成功结果。

## 验证

`tests/` 使用手写合成夹具验证缓存、取消、重连、范围与降级。Advance Playwright 验证页面接线；运行按[测试指南](../../docs/development/testing.md)。真实日志与 token 不进入 fixtures。
