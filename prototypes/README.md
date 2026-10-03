# UI 原型

原型都使用示例数据，与生产数据入口分别运行。Lite 与 Advance 已合为同一个 App，侧栏顶部一键切换：

| 原型 | 设计归属 | 入口 | 检查 |
| --- | --- | --- | --- |
| App（Lite + Advance） | Lite：genius-FXC；Advance：yhyfhgs | [单文件 HTML](advance/orbit-demo.html)、[源码](advance/src/)；`#l-home` 以 Lite 打开 | pnpm check:ui |
| Lite 原稿 | genius-FXC | [单文件 HTML](lite/orbit-benchmark-demo.html) | pnpm --filter @orbit/prototype-lite check |

App 的 HTML 是生成产物，编辑 src 后执行 `pnpm --filter @orbit/prototype-advance build`。版本切换与路由映射在 `src/js/26-edition.js`，Lite 四页在 `39-lite-pages.js`，两版共用的动效在 `37-motion.js`。Lite 页面只用已有组件拼装，差异仅限 `.lite` 作用域下的尺寸变体。截图 `node tools/shoot.mjs --ed lite` 可拍 Lite 四页。Lite 原稿保留原有独立 HTML 编辑方式，作为设计来源。

设计规范与画板位于 [docs/design](../docs/design/README.md)。正式 macOS UI 接入未来的 apps/desktop；原型通过不代表真实数据接入或安装包已完成。
