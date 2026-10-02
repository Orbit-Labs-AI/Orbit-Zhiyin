# Tandem 宣传片

约 51 秒、纯黑背景的产品宣传片。画面来自正在运行的 App（`../tandem-demo.html`），但每个镜头只显示其中一个组件：两份 App 轮流出镜，各自只保留当前组件，其余部分全部隐藏；组件旁配一段文字（眉题、重字、轻字三档）。转场是前后两个组件交叠的长缓动（上浮、纵深、横移），不使用闪白或震屏。配乐也是在同一套拍子网格上合成的。

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App，各配一组 `.cam`/`.rig` 镜头，`#fx` 放文字 |
| `promo.js` | 时间轴（以拍为单位，124 BPM）：`shot()` 定义一个组件镜头（出场方式、停留时的缓推、离场方式），`txt()` 定义遮罩上浮的文字 |
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
