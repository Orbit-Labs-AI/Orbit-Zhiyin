# Orbit 宣传片

约 54 秒、纯黑背景的 Orbit 产品宣传片。逐镜与关键帧脚本见 [STORYBOARD.md](STORYBOARD.md)，所学参考片的动效总结见 [REFERENCES.md](REFERENCES.md)。画面来自正在运行的 App（`../tandem-demo.html`）：两份 App 轮流出镜，每个镜头只显示其中一个组件。另外两样由宣传片自己绘制：
- **人格罗盘**：App 的 Orbit 表盘（`fp2SVG`：16 型扇区、按会话四维分布的 Agent 轨道与标志、人格之花），直接调用 App 的 `fpClassify` / `fpOrbit` / `bloom` / `typeP` / `agLogo` 绘制，App 改了表盘或花型，宣传片随之更新。
- **Orbit 标志**：与 `docs/design/logo/orbit-spec.json` 同一条锥形螺旋、同一套线宽规则（近粗远细、两端渐细、交叉处断开，按 `orbit.py` 计算）实时生成，任何视角都是 App 图标曲线的整体等比缩放。标志与字标一律白色。片头：描出 45° 标志 → 原样播放 `docs/design/logo/kit/motion/orbit-reveal.html` 的展开帧（绕轴转一周、转为 O 并展开 rbit·知音）→ 字母收回，O 转为俯视螺旋并旋转下潜进入功能展示。片尾：罗盘轨道收成圆环 → 圆环倾倒成带 5 颗 Agent 行星的轨道 → 沿轨道长出螺旋 → 回到 45° 标志，下方只有标语，不再放字标。

字体与 App 一致：SF Pro + PingFang SC、SF Mono，人格类型码用 SF Pro Rounded（`.tcode`）。

全片回答开场的两个问题。文案只描述产品能力，不出现个人数据（会话数、Agent 数量、节省的小时数、维度分值等）；画面里的界面是 App 自带的示例数据。
- **01 人格分析**：会话碎成粒子、按各自方位落进轨道 → 花苞随扫描转一圈后开花 → 在两个示例类型上各停约 1.1 秒（每次切换：旧花一瓣瓣收起、新花紧随其后一瓣瓣绽开，类型名称与字母都像字牌一样匀速滚动到下一型）→ 落定「指挥家 DIMV」并停约 5 秒 → 优势与盲点；外圈每个 Agent 的轨道与标志从圆环上均匀分布的位置出发，缓慢漂移，并随花瓣收起与绽开按各自速度同步转动。
- **02 推荐 → 效率**：点盲点旁的「建议 →」→ Skill / Prompt / Hook 三张真实建议逐张落下、各停约 2.1 秒，上方预计省时随每张滚动 → 看清改动（约 3 秒）→ 下一步 / 确认写入 → 直接看前后对比（约 4 秒）→ 「把时间还给你自己」。
随后直接进入收尾：罗盘的轨道收成圆环，倾倒成轨道、长出螺旋，回到 45° 标志。

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画 Orbit 标志与行星；`#fx` 放文字 |
| `promo.js` | 引擎（以拍为单位，132 BPM）：`shot()`/`tween()` 镜头、`txt()`/`tag()` 文字、`drive()`/`every()` 逐帧驱动、`clickAt()` 光标与点击 bloom、`drawCompass()` 罗盘、`orbitAt()` 标志、`stageXY()`/`elXY()` 屏幕坐标、虚拟时钟 |
| `scenes/05-light.js` / `light/` | 底层光影：路演 PPT 同款颗粒渐变光斑，按段落交叉淡换、缓慢漂移（拍号按 SHIFT 换算） |
| `scenes/00-kit.js` | 各场景共用的文字形式（`K.words`、`K.big`、`K.swap`、`K.blurIn`、`K.centerOut`、`K.scramble`、`K.decode`、`K.type`、`K.mark`、`K.strike`、`K.count`、`K.pop`）和圆形穿越门 `portal()` |
| `scenes/10-open.js` … `60-close.js`（v12 起没有 50） | 各段落，各自用 `scene(name, fn)` 注册，按文件名顺序运行；拍段与交接约定见 STORYBOARD.md |
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

预览：在仓库根启动任意静态服务器，打开 `prototypes/advance/promo/promo.html`（片头的字标展开帧从 `docs/design/logo/kit/motion` 读取），点击「播放」即可带配乐实时播放（`?t=<秒>` 可从中间开始，`?debug` 会显示当前拍号）。实时预览的效果取决于机器性能，最终成片以 `render.mjs` 的输出为准。

## 卡点原理

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头和字幕都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。

## 时间轴

片头（`scenes/10-open.js`）用成片拍号；之后各场景仍按各自的拍号书写，由引擎按 `promo.js` 的 `SHIFT` 表整体后移（情绪与人格 +5.9，推荐 +14.9，收尾 +5.4）；人格与推荐段内部再用 X/Y/Z、dA–dD 偏移后段拍号，每个镜头、文字、驱动与点击都记住所属场景的后移量。`music.py` 用同一张表。`render.mjs --only` 的拍号是成片拍号。
