# Orbit 宣传片

约 58 秒、纯黑背景的 Orbit 产品宣传片，逐镜脚本见 [STORYBOARD.md](STORYBOARD.md)。画面来自正在运行的 App（`../tandem-demo.html`）：两份 App 轮流出镜，每个镜头只显示其中一个组件。另外两样由宣传片自己绘制：
- **人格罗盘**：与 App 的指南针表盘共用几何，并接入 App 的数据。
- **Orbit 标志**：用和 `docs/design/logo` spiral 变体相同的锥形螺旋实时生成。

主线围绕两个核心功能：
- **分析**：数字飞进 KPI 卡 → 曲线向前 → 柱子逐根生长 → 柱状图卷成罗盘 → 16 种人格有快有慢地轮换，最后落到你的类型上。
- **推荐**：12 条建议逐条进场，节省时间累加到 22.7 h/月，再演示一次一键安装。
之后依次是轨迹回放、复盘、生成工坊、问本地 Agent、7 个功能快切，最后罗盘倾斜成轨道，收束为 Orbit 标志。

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画 Orbit 标志与行星；`#fx` 放文字 |
| `STORYBOARD.md` | 逐镜脚本：拍号、秒数、组件、镜头与动效、文字、声音 |
| `promo.js` | 时间轴（以拍为单位，124 BPM）：罗盘（`drawCompass`）、Orbit 标志（`orbitAt`）、`shot()` 定义组件镜头，`tween()` 定义镜头运动，`drive()` 逐帧驱动 App 图表（数字、折线、柱子、环、罗盘），`clickAt()` 定义光标点击，`txt()` 定义文字 |
| `music.py` | 用 numpy/scipy 合成配乐，输出到 `out/soundtrack.wav` |
| `render.mjs` | 在 Playwright 的虚拟时钟上逐帧截图，再用 ffmpeg 与配乐合成 MP4 |

## 用法

```bash
uv run --with numpy --with scipy python promo/music.py
node build.mjs && node promo/render.mjs            # -> promo/out/tandem-promo.mp4
```

`render.mjs` 的参数：`--fps 60`、`--scale 2`（按 2× 渲染后缩放到 1080p）、`--from/--to <秒>`、`--frames <目录>`（输出 JPG 序列而不是 MP4）、`--only 16,20.5`（只截取这几拍的画面，用于快速出联系表）、`--debug`（打印镜头目标的位置）。

预览：用任意静态服务器打开 `promo/promo.html`，点击「播放」即可带配乐实时播放（`?t=<秒>` 可从中间开始，`?debug` 会显示当前拍号）。实时预览的效果取决于机器性能，最终成片以 `render.mjs` 的输出为准。

## 卡点原理

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头和字幕都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。
