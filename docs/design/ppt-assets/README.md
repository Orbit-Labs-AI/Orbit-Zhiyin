# Orbit 路演组件素材

从现行 [Orbit 单文件原型](../../../prototypes/advance/orbit-demo.html) 提取完整页面和独立组件，供后续制作路演 PPT。保持现有设计与示例数据，提供透明背景 PNG、原始品牌 SVG、图表 SVG、素材索引与来源记录。

首次整理基于 `main` 的 `2b817a44`（2026-10-03）。每次重新导出都会在素材包的 `manifest.json` 记录当次完整提交 SHA；素材不代表真实用户统计或性能测试结果。

## 素材范围

| 目录 | 内容 |
| --- | --- |
| `pages/` | Advance 9 页、Lite 4 页的完整窗口，各有浅色和深色 |
| `components/` | 各页顶层卡片、指标、图表面板、独立人格罗盘、人格分享卡 |
| `desktop/` | 6 种桌面小组件、悬浮胶囊 5 种状态、展开态、菜单栏面板 |
| `controls/` | 侧栏、版本切换、工具栏、筛选、按钮、标签、开关等共用控件 |
| `flows/` | 设置六页、命令面板、分享预览、首次启动、来源选择、人格揭晓、安装预览与确认、问本地 Agent |
| `vectors/` | 从当前 DOM 导出的图表 SVG，解析颜色变量和可见样式 |
| `brand/` | [官方品牌文件](../brand.md)的原样副本 |
| `icons/` | 当前 UI 的图标路径，单独保存为 SVG |
| `sources/` | 可运行单文件 HTML，以及 26 份早期画板与 `canvas.json` 存档 |

`index.html` 可离线双击打开，支持中文搜索、类型筛选、浅深色筛选和逐个下载。`manifest.csv` / `manifest.json` 记录文件名、尺寸、主题、源文件、组件定位；`design-tokens.json` 记录当前配色与字体。

早期画板仍依赖 claude.ai Design 的运行时，只作源文件存档；导出图片使用的是现行可运行 UI。

## 重新提取

先按[开发指南](../../development/testing.md)安装仓库依赖与 Playwright Chromium。脚本复用 `prototypes/advance` 的 Playwright 依赖，不新增依赖包或锁文件：

```sh
pnpm install --frozen-lockfile
pnpm --filter @orbit/prototype-advance exec playwright install chromium
node prototypes/advance/build.mjs --check
node docs/design/ppt-assets/export.mjs
```

默认输出到忽略目录 `output/playwright/orbit-ppt-assets/`，PNG 按 3 倍像素密度导出。打开该目录下的 `index.html` 即可使用。大体积渲染结果和 ZIP 留在本地，不进入源码提交。

可选参数：

```sh
# 单页、单主题预览
node docs/design/ppt-assets/export.mjs --routes persona --themes dark --out output/playwright/persona-preview

# 共用控件与流程
node docs/design/ppt-assets/export.mjs --shared-only --themes light --out output/playwright/shared-preview

# 改为 2 倍分辨率
node docs/design/ppt-assets/export.mjs --scale 2 --out output/playwright/orbit-ppt-assets-2x
```

`PLAYWRIGHT_CHANNEL=chrome` 可使用本机 Chrome。已有独立 Playwright 运行环境时，也可将 `PLAYWRIGHT_MODULE` 设为它的模块绝对路径。这些机器路径不会写入素材清单。

## 放入 PPT

- 直接插入 PNG，保留纵横比。组件外部透明，组件内部保留原卡片底色、圆角和图表。
- 需要无损缩放时优先用品牌 SVG。图表 SVG 保留文字，显示依赖原字体；要求完全一致时用 PNG。
- Windows 导出的中文使用本机系统字体，与 macOS 的 PingFang 字形可能不同；拉丁标题和等宽数字使用页面字体。
- 页面图保留窗口的可见区域；各页的顶层卡片另有完整导出。列表、代码预览等组件内部仍保留原本的滚动范围。
- 所有数值、收益、社区人数和人格结果均来自 Demo 示例；引用时标注“示例界面”。

## 导出检查

脚本确认使用示例模式，检查目标非空与截图边界，收集浏览器脚本错误，并覆盖两套主题的所有页面卡片。每个组件截取后立即恢复 DOM 样式，避免影响随后弹出的对话框。完成后仍需浏览素材索引，检查圆角、文字、长列表和图表。品牌副本应与源文件一致，PNG 的实际尺寸应与 manifest 相符。
