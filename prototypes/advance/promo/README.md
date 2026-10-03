# Orbit 宣传片

40 秒（88 拍，132 BPM）、纯黑背景的 Orbit 产品宣传片（v17）。逐镜、关键帧与交接见 [STORYBOARD.md](STORYBOARD.md)，参考片的动效总结见 [REFERENCES.md](REFERENCES.md)。

全片只有一套 Agent 点：5 个 Agent 的圆形标志（`agBadge`，即 App 的 `agLogo`）从第一拍弹出，一路变换编队（散布 → 弧形 → 圆环 → 标志外的轨道 → 罗盘外圈 → 竖列 → 合并为一 → 圆环 → 一行），把各段连成一条线。另外三样由宣传片自己绘制：
- **Orbit 标志**：与 `docs/design/logo/orbit-spec.json` 同一条锥形螺旋、同一套线宽规则（`orbitSVG`），任何视角都是 App 图标曲线的整体等比缩放，不重画、不改线宽，一律白色。
- **人格罗盘**：按 App 0.0.4 的表盘与人格之花绘制（`drawCompass`，调用 App 的 `fpClassify` / `fpOrbit` / `bloom` / `typeP` / `agLogo`），App 改了表盘，宣传片随之更新；罗盘自带的标志关掉，由 Agent 点层骑在外圈上画。
- **App 图标、输入框与气泡**：片头的 12 个线性图标、输入框和 prompt / 纠正气泡。

其余画面来自正在运行的 App（`../orbit-demo.html`）：两份 App 轮流出镜，每个镜头只显示一个组件（建议卡、会话轨迹卡、生成工坊），从不出现完整窗口。文案只描述产品能力；节省一律是占比（App 的 `recPct` / `fmtPct`），不出现小时或个人数字。

字体与 App 一致：SF Pro + PingFang SC、SF Mono，人格类型码用 SF Pro Rounded（`.tcode`）。

## 时间轴

| 段 | 文件 | 拍 | 秒 | 内容 | Agent 点 |
| --- | --- | --- | --- | --- | --- |
| 1a | `10-intro.js` | 0–4.2 | 0–1.9 | 「现在，每天无数人在使用 AI Agent」 | 依次弹出、散布 |
| 1b | `10-intro.js` | 4–8.8 | 1.8–4.0 | 「从想法到交付」：输入框打字发送、各家 prompt 气泡，12 个 App 图标迸出到光环 | 弧形 |
| 1c | `10-intro.js` | 8.6–12.6 | 3.9–5.7 | 「We Are Redesigning Everything」：图标随大字吸近、转向、飞出 | 退到四周 |
| 1d | `15-redesign.js` | 12.4–18.0 | 5.6–8.2 | 「我们认为，人与 AI 的协作，也值得被重新设计」：纠正指令气泡越来越密 | 回到弧形 |
| 1e | `15-redesign.js` | 17.4–22.0 | 7.9–10.0 | 「So，We Redesign for everyone」（全片第一个峰值） | 展开成 R 420 圆环 |
| 2 | `20-orbit.js` | 21.6–28.2 | 9.8–12.8 | 圆环收紧 → 俯视螺旋长出 → 立起成 45° 标志 → 翻平转半圈交给罗盘 | R 300 → 标志外的倾斜轨道 → 罗盘 |
| 3 | `30-persona.js` | 26.4–40.4 | 12.0–18.4 | 01 协作人格：罗盘成形、花苞落在你的类型；左移后右侧竖向滚动分析列，揭晓 DIMV | 骑在罗盘外圈 |
| 4 | `40-recs.js` | 39.4–55.4 | 17.9–25.2 | 02 优化建议：6 条真实建议卡竖向滚动，类型大字、连到 Agent，协作时间 / Token 两个累计占比 | 左侧竖列 |
| 5 | `50-tools.js` | 55.0–70.0 | 25.0–31.8 | 5 个点合并为一 → 会话轨迹（播放头走过阶段）→ 生成工坊（点「开始生成」，写出 SKILL.md） | 合并为一 |
| 6 | `60-close.js` | 69.4–77.4 | 31.5–35.2 | 散开成圆环 → 罗盘 → 圆环长出螺旋，立成 45° 标志 | 圆环 → 罗盘 → 圆环 |
| 7 | `60-close.js` | 77.0–88 | 35.0–40.0 | 标志上移，「Orbit」与「An Assistant Redesign for everyone & every agent」 | 在标语下方排成一行 |

配乐三处峰值：b18.2（「So，」）、b52（最后一条建议落定）、b79（片尾）。

## 文件

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画标志；`#fx` 放文字 |
| `promo.js` | 引擎（以拍为单位，132 BPM）：`shot()`/`tween()` 镜头、`txt()`/`tag()` 文字、`drive()`/`every()` 逐帧驱动、`clickAt()` 光标与点击 bloom、`drawCompass()` 罗盘、`markAt()`/`markRing()`/`MARK` 标志姿态、`stageXY()`/`elXY()` 屏幕坐标、虚拟时钟 |
| `scenes/00-kit.js` | 共用的文字形式（`K.words`、`K.big`、`K.swap`、`K.blurIn`、`K.centerOut`、`K.decode` 等）与 `hash01` |
| `scenes/02-agents.js` | Agent 点层 AGD：`AGD.key(b, form, o)` 编队关键帧（pts / ring / orbit / compass / column / merge / row …）、`AGD.chat` 输入框、`AGD.bubble` 气泡、`AGD.link` 连线、`AGD.glow`、`AGD.back` 点下方的绘制层、`AGD.pos` |
| `scenes/05-light.js` / `light/` | 底层光影：三团常驻颗粒渐变光体，各走各的连续轨迹，不读取任何场景对象 |
| `scenes/10-intro.js` … `60-close.js` | 各段落（见上表），各自用 `scene(name, fn)` 注册，按文件名顺序运行；只写自己拍段的关键帧，交接约定见 STORYBOARD.md「转场关键帧」 |
| `music.py` | 用 numpy/scipy 在同一拍网格上合成配乐（88 拍 + 1 秒尾音），输出 `out/soundtrack.wav` |
| `render.mjs` | 在 Playwright 的虚拟时钟上逐帧截图，再用 ffmpeg 与配乐合成 MP4 |

## 用法

```bash
uv run --with numpy --with scipy python promo/music.py
node build.mjs && node promo/render.mjs            # -> promo/out/orbit-promo.mp4
```

`render.mjs` 的参数：`--out <file.mp4>`、`--fps 60`、`--scale 2`（按 2× 渲染后缩放到 1080p）、`--from/--to <秒>`、`--frames <目录>`（输出 JPG 序列而不是 MP4）、`--only 16,20.5`（只截取这几拍的画面，用于快速出联系表）、`--debug`。环境变量 `PROMO_PAGE=<文件名>` 可以渲染同目录下的另一个页面。

预览：在仓库根启动任意静态服务器，打开 `prototypes/advance/promo/promo.html`，点击「播放」即可带配乐实时播放（`?t=<秒>` 从中间开始，`?debug` 显示当前拍号）。实时预览的效果取决于机器性能，最终成片以 `render.mjs` 的输出为准。

## 卡点原理

所有场景、`music.py` 与 `render.mjs --only` 共用成片拍号（`SHIFT` 表为空，保留只为兼容）。片长由 `60-close.js` 设置的 `END = 88` 决定（`PROMO.duration = END × BEAT` = 40 秒），`music.py` 的 `END` 与之相同。

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头、文字、Agent 点和标志都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。
