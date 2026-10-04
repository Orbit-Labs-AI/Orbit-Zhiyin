# 人格之花与表盘素材

素材来自当前统一原型的绘制函数，供 App、文档和展示复用。人格描述算法见[画像说明](../../modules/analytics/profiling.md)；这里仅维护视觉与导出规则。

## 16 型花

| [`flowers/svg/`](kit/flowers/svg/DIMV-light.svg) | 16 型花：`<类型码>-light`、`-dark` 为两色（墨色主瓣 + 浅灰小瓣）；`-ink` 为单色墨稿（`#17181b`），供印刷、描摹或改色 | SVG，180 × 180 方形视框，透明底 |
| [`flowers/png/`](kit/flowers/png/DIMV-light-512.png) | 浅色、深色两套花 | PNG 512、128，透明底 |
| [`sheet/`](kit/sheet/types-light.png) | 16 型总览 4 × 4：花、类型码（App 的 `.tcode`，SF Pro Rounded）与中文名，铺在 App 纸面 / 深色底上 | PNG 1968 × 2060 |
| [`dial/`](kit/dial/dial-light.svg) | 画像页表盘，示例数据，入场动画结束后的静止状态 | SVG（以圆心为中心的方形视框，包住表盘外的三角）；PNG 1440 × 1440（720 px 的 2 倍）；透明底 |

每朵花由旋转对称的同形主瓣、可选浅灰小瓣和花心构成，没有单独领瓣。M/F、I/P、D/S、V/T 分别影响瓣数、旋卷、瓣心比例和花心形式；App 中强度可调整比例。正式形状以原型函数和 kit 为准，不在素材上重画。

## 表盘

![人格表盘示例](kit/dial/dial-light.png)

外框排列 16 型，每个 Agent 一条独立曲线，共用基线和高度尺度；徽章表示其会话平均方向。内盘花与类型指针对应当前选择。素材中的会话分布是 Demo 示例，使用时标注“示例数据”。

SVG 保留透明区域、颜色和变换，表盘文字可能依赖系统字体和遮罩支持；跨软件需要固定外观时选 PNG。花心透明处会露出底色，不应误填成白色。

## 重新导出

先准备原型依赖与 Chromium，再从根执行：

```sh
pnpm --filter @orbit/prototype-advance build
python3 scripts/heavy.py node docs/design/persona/export.mjs
```

`--check` 在临时目录比对 SVG，`--out <目录>` 改输出位置。PNG 受字体和浏览器影响，不能用不同机器的像素差异判断算法变化。macOS 字体注册和其他系统回退按脚本提示处理。完整产物清单见 [manifest](kit/manifest.json)。
