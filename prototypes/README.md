# Orbit 界面源码与演示

`advance` 是当前 App 共用的 Web UI：Lite 与 Advance 的页面已合并到同一套侧栏（精简版也保留全部入口），在「显示 → 高级模式」或 设置 → 通用 里打开完整明细布局；两个版式共用组件、数据适配和动效。`lite` 保留最初的独立设计原稿，不再作为另一套产品组件体系扩展。

| 目录 | 用途 | 入口 |
| --- | --- | --- |
| `advance` | 统一 App 源码与生成 HTML | [orbit-demo.html](advance/orbit-demo.html)、[src](advance/src/) |
| `lite` | `genius-FXC` 的 Lite 设计来源 | [原稿](lite/orbit-benchmark-demo.html) |
| `shared` | 共用 live 请求、状态和 SSE 客户端 | [OrbitLive](shared/README.md) |

## 界面状态与语言

- 默认英文；`View → Language`（或 设置 → 语言）切换中文。文案仍写在渲染代码里，`02-i18n.js` 在渲染后用 `03-i18n-dict.js` 的字典与规则替换，未覆盖的文案保持原文。
- `26-edition.js` 管版本状态与页面映射（高级模式只是同一批页面的版式开关，侧栏不再有 Lite / Advance 切换条）；`39-lite-pages.js` 组合精简页面；共用样式和动效优先复用。

## 两种数据模式

独立打开 HTML 使用示例数据，可直接体验交互。由 gateway 的 `/app` 或 `/lite` 托管时进入 live 模式，原生宿主也使用此路径。当前已有真实 App 接线，不能再将整个目录描述为“等待未来接入”。

## 修改与验证

```sh
pnpm --filter @orbit/prototype-advance build
python3 scripts/heavy.py pnpm check:ui
```

修改 `advance/src/` 后重新生成 HTML，不手改生成产物。默认使用 Playwright 管理的 Chromium；本机已安装 Chrome、或 Chromium 下载受限时，用 `PLAYWRIGHT_CHANNEL=chrome` 运行同一批测试。界面语言与版式的覆盖见 [测试说明](advance/TESTING.md)。

Lite 设计来自 `genius-FXC`，Advance 来自 `yhyfhgs`。视觉规范和素材在[设计文档](../docs/design/README.md)，浏览器检查见[测试说明](advance/TESTING.md)，原生运行见[桌面宿主](../apps/desktop/README.md)。
