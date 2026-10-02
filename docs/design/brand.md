# Orbit 品牌：名称与标志

状态：现行 · 维护者 `yhyfhgs` · 2026-10-02 起生效 · 适用：Lite / Advance（同一个 App）

## 名称

产品名为 **Orbit**，取代暂定名 Tandem / 同频。界面可见的文字、文档正文、路演与宣传材料一律写 Orbit。

代码标识暂不改名，文档引用它们时按原样书写：

| 类别 | 保持原样的标识 |
| --- | --- |
| Python 包与 CLI | `tandem_backend`、`tandem_data`、`tandem_catalog`，命令 `tandem`、`tandem-data` |
| 数据目录与环境变量 | `~/Library/Application Support/Tandem/`、`.tandem/`、`TANDEM_HOME`、`tandem.db` |
| 前端与客户端 | `TandemLive`、`TandemCatalogClient`、`@tandem/*` workspace 包名、`X-Tandem-Freshness` 响应头、localStorage 前缀 |
| 文件名 | `prototypes/advance/tandem-demo.html`、`prototypes/lite/tandem-benchmark-demo.html` |

规划中的 App bundle 写作 `Orbit.app`。若日后统一改代码标识，需要同时迁移已有数据目录，届时另行记录。

## 标志

标志是一条 1.6 圈的锥形螺旋线：半径由外向内收、同时沿轴向抬升，斜看（yaw 20°、pitch 45°）时内圈从外环下方穿过，像一条正在收拢的轨道。线条语言沿用此前的莫比乌斯带与洛伦茨吸引子版本：一笔画成，近处粗、远处细，投影交叉处较远的一支断开，两端渐细收笔，只用一种颜色。

- 线色是低饱和板岩灰 `#5f6b6f`，App 原型中为品牌 token `--orbit`（浅色 `#5f6b6f`，深色 `#a3adb0`），只用于标志、罗盘指针北半与 00 基准三角。
- App 图标是暖纸底（`#f5f4f0`）圆角方块，标志居中。
- App 原型的菜单栏图标、App 图标与 Genesis 首次启动由 `prototypes/advance/src/js/00-utils.js` 的 `orbitGeom` / `orbitMark` 按同一组参数实时绘制，16 px 下仍清晰。

| 文件 | 用途 |
| --- | --- |
| [`logo/orbit-mark.svg`](logo/orbit-mark.svg) | 主标志，透明底、紧凑画布 |
| [`logo/orbit-mark-light.svg`](logo/orbit-mark-light.svg) | 浅色线（暖纸色），用于深色底 |
| [`logo/orbit-mark-small.svg`](logo/orbit-mark-small.svg) | 线宽拉平加粗，用于 48 px 以下或 favicon |
| [`logo/orbit-icon.svg`](logo/orbit-icon.svg)、[`logo/orbit-icon.png`](logo/orbit-icon.png) | 方形 App 图标，1024 px |

![Orbit App 图标](logo/orbit-icon.png)

文件由 [`logo/generate.py`](logo/generate.py) 生成：`python3 docs/design/logo/generate.py`，纯 Python、无第三方依赖、结果可复现。圈数、起止半径、轴向抬升、视角、线宽和交叉留白都是脚本顶部的常量；断口是真正断开的，可直接放在任意底色上。PNG 由浏览器截图导出，改 SVG 后需同步更新。

## 备选与历史版本

同一脚本一并生成两个洛伦茨吸引子（σ=10, ρ=28, β=8/3）版本，文件组成相同（mark、light、small、icon）：

| 版本 | 位置 | 曲线 |
| --- | --- | --- |
| 洛伦茨 | [`logo/variants/lorenz/`](logo/variants/lorenz/orbit-mark.svg) | 一段左右两翼各绕两圈的吸引子轨道；改名前的 Tandem 主标志 |
| 洛伦茨（复杂度略增） | [`logo/variants/rich/`](logo/variants/rich/orbit-mark.svg) | 同一段轨道多取一圈，右翼多绕一圈 |

更早的莫比乌斯带版本见 git 历史（`391203a` 及更早）。
