# Orbit 宣传片

约 55 秒、纯黑背景的 Orbit 产品宣传片。逐镜与关键帧脚本见 [STORYBOARD.md](STORYBOARD.md)，所学参考片的动效总结见 [REFERENCES.md](REFERENCES.md)。画面来自正在运行的 App（`../tandem-demo.html`）：两份 App 轮流出镜，每个镜头只显示其中一个组件。另外两样由宣传片自己绘制：
- **人格罗盘**：与 App 的指南针表盘共用几何，并接入 App 的数据。
- **Orbit 标志**：用和 `docs/design/logo` spiral 变体相同的锥形螺旋实时生成。

全片回答开场的两个问题：
- **01 人格分析**：数字碎成粒子落进罗盘 → 指针扫过 16 型 → 四条证据逐个锁定字母 → 揭晓「指挥家 DIMV」→ 优势与盲点。
- **02 推荐 → 效率**：点盲点旁的「建议 →」打开推荐 → 每条建议的节省时间逐张汇入 22.7 h/月 → 一键安装 → 7 天后前后对比 → 「每月多出 22.7 小时」。
之后快速带过轨迹回放、生成工坊、问本地 Agent 和桌面上的各项功能，最后罗盘收回成 Orbit 标志。

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画 Orbit 标志与行星；`#fx` 放文字 |
| `promo.js` | 引擎（以拍为单位，124 BPM）：`shot()`/`tween()` 镜头、`txt()`/`tag()` 文字、`drive()`/`every()` 逐帧驱动、`clickAt()` 光标与点击 bloom、`drawCompass()` 罗盘、`orbitAt()` 标志、`stageXY()`/`elXY()` 屏幕坐标、虚拟时钟 |
| `scenes/00-kit.js` | 各场景共用的文字形式（`K.words`、`K.big`、`K.swap`、`K.blurIn`、`K.centerOut`、`K.scramble`、`K.decode`、`K.type`、`K.mark`、`K.strike`、`K.count`、`K.pop`）和圆形穿越门 `portal()` |
| `scenes/10-open.js` … `60-close.js` | 各段落，各自用 `scene(name, fn)` 注册，按文件名顺序运行；拍段与交接约定见 STORYBOARD.md |
| `STORYBOARD.md` | 逐镜与关键帧：拍号、秒数、组件、镜头与动效、文字形式、声音、交接 |
| `REFERENCES.md` | 参考片的节奏、转场、文字、组件手法，以及 v6 复盘 |
| `music.py` | 用 numpy/scipy 合成配乐，输出到 `out/soundtrack.wav` |
| `render.mjs` | 在 Playwright 的虚拟时钟上逐帧截图，再用 ffmpeg 与配乐合成 MP4 |

## 用法

```bash
uv run --with numpy --with scipy python promo/music.py
node build.mjs && node promo/render.mjs            # -> promo/out/tandem-promo.mp4
```

`render.mjs` 的参数：`--fps 60`、`--scale 2`（按 2× 渲染后缩放到 1080p）、`--from/--to <秒>`、`--frames <目录>`（输出 JPG 序列而不是 MP4）、`--only 16,20.5`（只截取这几拍的画面，用于快速出联系表）、`--debug`（打印镜头目标的位置）。环境变量 `PROMO_PAGE=<文件名>` 可以渲染同目录下的另一个页面（例如只加载某几个场景的测试页）。

预览：用任意静态服务器打开 `promo/promo.html`，点击「播放」即可带配乐实时播放（`?t=<秒>` 可从中间开始，`?debug` 会显示当前拍号）。实时预览的效果取决于机器性能，最终成片以 `render.mjs` 的输出为准。

## 卡点原理

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头和字幕都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。
