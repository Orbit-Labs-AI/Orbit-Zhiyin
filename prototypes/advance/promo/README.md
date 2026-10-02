# Tandem 宣传片

约 51 秒、纯黑背景的产品宣传片。画面来自正在运行的 App（`../tandem-demo.html`），每个镜头只显示其中一个组件：两份 App 轮流出镜，各自只保留当前组件，其余部分全部隐藏。

画面语言参考了 Apple 的发布片和 What a Story 的 SaaS 发布片：
- **衔接**：前后场景尽量共用同一个元素或同一个运动方向。大数字滚动后飞进 KPI 卡；镜头推进卡片，看折线向前画出；镜头继续向右滑进柱状图，柱子逐根生长；柱状图旋转卷成 24 小时指纹环；环心变成罗盘，指针旋转后停在人格代码上；轨迹 → 启示 → 问 Agent 是一条向上推进的纵向信息流。
- **文字**：分三档，等宽眉题、银色主标题、橙色副标题；开场句子逐词叠出。
- **转场**：交叠的长缓动，配合倾斜平面入场和光标点击，不使用闪白或震屏。

配乐在同一套拍子网格上合成：数字滚动对应棘轮声，每根柱子对应一个拨弦音，每个小时格对应一个提示音，指针每扫过一个代码就有一声滴答。

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App，各配一组 `.cam`/`.rig` 镜头，`#fx` 放文字 |
| `promo.js` | 时间轴（以拍为单位，124 BPM）：`shot()` 定义组件镜头，`tween()` 定义镜头运动，`drive()` 逐帧驱动 App 图表（数字、折线、柱子、环、罗盘），`clickAt()` 定义光标点击，`txt()` 定义文字 |
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
