# Demo 与统一界面

当前 App 界面源位于 `prototypes/advance/src/`，构建为单文件 `orbit-demo.html`。独立打开是示例模式，由 gateway 托管则进入 live 模式；原生宿主使用同一套页面。

## 查看

浏览器直接打开 [orbit-demo.html](../../prototypes/advance/orbit-demo.html)，侧栏顶部切换 Lite / Advance。示例人格、用量、工具调用、收益与实时状态仅用于展示。真实数据入口见[开发环境](../development/setup.md)。

Lite 聚焦常用页面；Advance 展开概览、协作人格、情绪语义、会话轨迹、项目习惯、工具调用、建议、资源库和生成等流程。菜单栏、HUD、小组件与分享使用共用的设计语言，原生 App 中由真实宿主承载系统表面。

## 修改

```sh
pnpm --filter @orbit/prototype-advance build
python3 scripts/heavy.py pnpm check:ui
```

编辑源文件，生成 HTML。版本/路由、页面组合、通用动效和 live 绑定分别有模块，不在 Lite 另建平行组件。共享客户端更新按 [OrbitLive](../../prototypes/shared/README.md)同步。

## 视觉与数据边界

主从窗格按可用宽度独立或整页滚动；状态、空值与筛选需保持可理解。品牌几何原样引用，类型文案与后端一致；动画遵守减少动态效果设置。具体行为由当前源码和测试定义，旧画板不能覆盖真实数据合同。

历史 Lite 原稿保留在 [prototypes/lite](../../prototypes/lite/orbit-benchmark-demo.html)。展示图与宣传片可能绑定不同版本，使用前查看各自 manifest 或说明。发布/部署不由修改本页自动触发。
