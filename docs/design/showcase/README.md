# Orbit 展示图

状态：现行 · 维护者 `yhyfhgs` · 适用：Lite / Advance

路演与介绍用的展示图：主视觉（协作人格罗盘 + Orbit·知音 字标）与 10 张核心功能、组件和交互示意。罗盘、16 型花与字标取自[人格素材](../persona/README.md)和[标志素材](../logo/kit/manifest.json)的原样文件，界面截图与动画帧取自现行原型 `prototypes/advance/orbit-demo.html`（示例数据），不重画。

![主视觉](png/orbit-hero-light.png)

| 文件 | 内容 |
| --- | --- |
| [`orbit-hero-light.png`](png/orbit-hero-light.png) · [`-dark`](png/orbit-hero-dark.png) · [`-square`](png/orbit-hero-square.png) | 主视觉：罗盘 + 字标 + 标语，浅色 / 深色 16:9，方形 1:1 |
| [`orbit-01-dial-anatomy.png`](png/orbit-01-dial-anatomy.png) | 罗盘怎么读：三角、外框 16 型、Agent 曲线、人格之花、Agent 徽章 |
| [`orbit-02-sixteen-types.png`](png/orbit-02-sixteen-types.png) | 四个维度与 16 型之花 |
| [`orbit-03-how-it-works.png`](png/orbit-03-how-it-works.png) | 工作原理：找到会话 → 本机整理 → 看见自己 → 动手改进 |
| [`orbit-04-first-launch.png`](png/orbit-04-first-launch.png) | 首次启动四步与 Genesis 揭晓逐帧 |
| [`orbit-05-bloom-switch.png`](png/orbit-05-bloom-switch.png) | 人格切换：收起再绽开的逐帧与时间轴 |
| [`orbit-06-install-loop.png`](png/orbit-06-install-loop.png) | 建议闭环：预览 → 确认 → 撤销 → 7 天追踪 |
| [`orbit-07-session-replay.png`](png/orbit-07-session-replay.png) | 会话轨迹回放的 7 个要点 |
| [`orbit-08-desktop.png`](png/orbit-08-desktop.png) | 菜单栏面板、悬浮胶囊五种状态、桌面小组件 |
| [`orbit-09-share-cards.png`](png/orbit-09-share-cards.png) | 周卡 / 月卡 / 季卡 / 全时卡 |
| [`orbit-10-lite-advance.png`](png/orbit-10-lite-advance.png) | Lite 与 Advance：同一个 App |

16:9 为 3840 × 2160，方形为 3200 × 3200。所有数值与人格结果均为 Demo 示例，引用时标注“示例界面 / 示例数据”。

## 重新生成

原型或素材改动后重新导出（复用 `prototypes/advance` 的 Playwright，macOS 上自动注册系统的 SF Pro Rounded）：

```sh
node docs/design/showcase/capture.mjs   # 界面截图与动画帧 → output/playwright/orbit-showcase/ui/
node docs/design/showcase/export.mjs    # 按 boards.html 排版逐张导出 → output/playwright/orbit-showcase/
cp output/playwright/orbit-showcase/orbit-*.png output/playwright/orbit-showcase/manifest.json docs/design/showcase/png/
```

版式在 [`boards.html`](boards.html)，可加 `--only 01-dial-anatomy` 只导出一张。截图保留元素自身的阴影并在 `shots.json` 记录外边距，版面里写的宽高指内容本身；07 页的标注坐标是会话页窗口内的像素，会话页布局改动后需要同步调整。
