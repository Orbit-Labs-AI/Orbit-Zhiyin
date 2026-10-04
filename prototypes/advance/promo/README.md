# Orbit 宣传片

> 版本化展示资料：人格、用量与节省比例是示例叙事，不是实际用户收益证据；时间轴与镜头以本版场景源码为准。

约 60 秒（131.7 拍，132 BPM，1 拍 = 0.4545 秒，成片 ≈ 59.9 秒）、纯黑背景的 Orbit 产品宣传片（v17.6）。现状与逐段关键拍见 [STORYBOARD.md](STORYBOARD.md) 开头的「v17.6」一节（其后各节是历史记录），参考片的动效总结见 [REFERENCES.md](REFERENCES.md)。拍号以 `scenes/*.js` 为准。

全片只有一套 Agent 点：5 个 Agent 的圆形标志（`agBadge`，即 App 的 `agLogo`）从第一拍弹出，始终是一个紧凑的小组、也就是视线中心，一路变换编队，把各段连成一条线：簇 → 笔尖（∪ 弧）→ 窄弧 → 光标 → 窄弧 → R 420 圆环 → 标志外的倾斜轨道 → 字标下一行 → 罗盘外圈（随 Agent 曲线公转）→ 左侧短列 → 合并为一（骑播放头、当光标、当生成源）→ 螺旋放出成环 → 罗盘 → 圆环 → 笔头后的一串 → 图标下一行 → 标语下一小行。另外几样由宣传片自己绘制：

- **Orbit 标志**：与 `docs/design/logo/orbit-spec.json` 同一条锥形螺旋、同一套线宽规则（`orbitSVG`），任何视角都是 App 图标曲线的整体等比缩放，不重画、不改线宽，白色（App 图标黑夜版）。
- **字标「Orbit·知音」**：`scenes/03-wordmark.js` 原样读取 logo kit 的 `docs/design/logo/kit/motion/orbit-reveal.html`（预计算的转身帧与字母路径），标志绕自身轴转一圈成为字标的 O，「rbit·知音」逐字升起；片头白色，片尾转身时由白过渡到深色底字标的香槟黄 `#d6c7a1`。
- **人格罗盘**：按 App 0.0.4 的表盘与人格之花绘制（`drawCompass`，调用 App 的 `fpClassify` / `fpOrbit` / `bloom` / `typeP` / `agLogo`），罗盘自带的标志关掉，由 Agent 点层骑在外圈上画。
- **App 图标、输入框与气泡**：片头的 12 个线性图标、输入框、prompt / 纠正指令气泡。

其余画面来自正在运行的 App（`../orbit-demo.html`）：两份 App 轮流出镜，每个镜头只显示一个组件（建议卡、会话轨迹卡、生成工坊），从不出现完整窗口。文案只描述产品能力；节省一律是占比（App 的 `recPct` / `fmtPct`），不出现小时或个人数字。字体与 App 一致：SF Pro + PingFang SC、SF Mono，人格类型码用 SF Pro Rounded（`.tcode`）。

## 场景

每个场景文件用自己的拍号（场景拍）；`promo.js` 的 `SHIFT` 把它整体推后，**成片拍 = 场景拍 + SHIFT**（见下文「拍号与 SHIFT」）。

| 文件 | SHIFT | 场景拍 | 成片拍 | 秒 | 交出 |
| --- | --- | --- | --- | --- | --- |
| `10-intro.js` | 0 | 0–19.65 | 0–19.65 | 0–8.9 | 光标；b18.7 起的窄弧 key 归 15-redesign |
| `15-redesign.js` | 6.9 | 11.8–27.4 | 18.7–34.3 | 8.5–15.6 | 场景 b26.0（成片 32.9）的 R 420 圆环交给 20-orbit，虚线圆随之收紧后淡出 |
| `20-orbit.js` | 11.3 | 21.6–33.8 | 32.9–45.1 | 15.0–20.5 | 场景 b31.3 起 compass key，b33.0 标志翻平落在罗盘描边光起点（成片 42.6 / 44.3） |
| `30-persona.js` | 16.9 | 26.4–45.4（罗盘画到 47.5） | 43.3–62.3 | 19.7–28.3 | CO = 场景 b45.4（成片 62.3）：徽章从公转外圈剥离（CO − .9 起，由 40-recs 写） |
| `40-recs.js` | 22.9 | 39.4–63.1（剥离自 38.5） | 62.3–86.0 | 28.3–39.1 | 场景 b63.0（成片 85.9）短列合并为一 |
| `50-tools.js` | 30.9 | 55.0–75.2 | 85.9–106.1 | 39.0–48.2 | 场景 b75.2（成片 106.1）合并点回到画面中心 |
| `60-close.js` | 36.9 | 69.2–94.8 | 106.1–131.7 | 48.2–59.9 | 设 `END = TURN0 + 13.0 = 94.8`（场景拍）→ 片长 131.7 拍 |

## 时间轴

| 段 | 文件 | 成片拍 | 秒 | 内容 | Agent 点 |
| --- | --- | --- | --- | --- | --- |
| 1a | `10-intro.js` | 0–6.6 | 0–3.0 | 小字「用 AI Agent，」/ 大字「正在成为每个人的日常」逐词落定，「日常」橙色盖章（b2.6） | 簇弹出 → ∪ 笔尖跟着最新的词 |
| 1b | `10-intro.js` | 6.6–13.2 | 3.0–6.0 | 「从想法到交付」：输入框从点里长出、三次发送、各家 prompt 气泡；12 个 App 图标迸到光环（b11.35） | ∩ 窄弧 |
| 1c | `10-intro.js` | 13.2–19.65 | 6.0–8.9 | 「We Are Redesigning Everything」逐词（b13.8–15.3），下方「人们正在用 Agent 重新设计一切」；图标被吸近、转向、飞出 | 光标 |
| 1d | `15-redesign.js` | 18.7–27.6 | 8.5–12.5 | 「但，」/「人与 Agent 的交互本身，」（荧光笔）/「也需要被重新定义」；纠正指令气泡越来越密 | 窄弧，输入框从中生出 |
| 1e | `15-redesign.js` | 27.2–34.3 | 12.4–15.6 | 「So，我们做了一个 Assistant」→ 环内三行硬切 Redesign / Agent Workflow / for everyone（b28.8 / 29.2 / 29.6），全片第一个峰值 | R 420 圆环 |
| 2 | `20-orbit.js` | 32.9–45.1 | 15.0–20.5 | 圆环收紧 → 俯视螺旋 → 立成 45° 标志 → kit 转身成「Orbit·知音」（b35.9–39.9）+「你的 AI 协作复盘助手」（b38.0）→ 收字、O 转回 → 翻平交给罗盘 | R 300 → 倾斜轨道 → 字标下一行 → 轨道 → 罗盘 |
| 3 | `30-persona.js` | 43.3–62.3 | 19.7–28.3 | 01 协作人格：罗盘成形、花落在 SIFT；左移后右列滚动分析，花一瓣瓣换成 DIFT → DIMT → DIMV（落定 b58.6），揭晓 | 罗盘外圈，随各自的曲线公转 |
| 4 | `40-recs.js` | 61.4–86.0 | 27.9–39.1 | 徽章按行剥离成左列，前三行各连出引言卡一行「02 · 优化建议 / 根据你的使用习惯，智能推荐 / 提高效率」；6 条建议卡滚动（b68.9 起每 3 拍一条），协作时间 / Token 两个累计占比 | 左侧短列，连到的点前移 |
| 5 | `50-tools.js` | 85.9–106.1 | 39.0–48.2 | 合并为一 → 会话轨迹（5 个阶段）→ 生成工坊：点到「开始生成」按下（b99.7），写出 SKILL.md | 合并点 |
| 6 | `60-close.js` | 106.1–118.7 | 48.2–54.0 | 螺旋放出成环 → 罗盘 → 收回圆环 → 曲线一笔画出（b112.5–115.5）→ 转身倒成 45° 图标、停留 | 环 → 罗盘 → 环 → 笔头后一串 → 图标下一行 |
| 7 | `60-close.js` | 118.7–131.7 | 54.0–59.9 | kit reveal 成「Orbit·知音」→「An Assistant Redesign for everyone & every agent」（b122.7）→ b129.9 起淡到全黑 | 标语下一小行 |

## 文件

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画标志；`#fx` 放文字；按文件名顺序加载 `scenes/*.js` |
| `promo.js` | 引擎（以拍为单位，132 BPM）：`SHIFT` 表与 `END`、`shot()`/`tween()` 镜头、`txt()`/`tag()` 文字、`drive()`/`every()` 逐帧驱动、`clickAt()` 点击 bloom、`drawCompass()` 罗盘、`markAt()`/`markRing()`/`MARK` 标志姿态、`stageXY()`/`elXY()` 屏幕坐标、虚拟时钟 |
| `scenes/00-kit.js` | 共用的文字形式（`K.words`、`K.big`、`K.swap`、`K.blurIn`、`K.centerOut`、`K.decode`、`K.mark` 等）与 `hash01` |
| `scenes/02-agents.js` | Agent 点层 AGD：`AGD.key(b, form, o)` 编队关键帧（ring / arc / column / orbit / compass / merge / row …）、`AGD.follow`、`AGD.chat` 输入框、`AGD.bubble` 气泡、`AGD.link` 连线、`AGD.pulse`、`AGD.glow`、`AGD.back` 点下方的绘制层、`AGD.pos` / `AGD.centroid` |
| `scenes/03-wordmark.js` | 字标展开 helper（不注册场景）：`WORDMARK.place(pose)` 把 kit 第 0 帧对齐到 `orbitSVG` 的 ICON 姿态，`WORDMARK.svg(o)` 按转身进度 `v`、字母起落拍与 `offRate` / `color` 画进它自己插在 `#orbit` 之上的 `#wordmark` 层；帧加载完才启动脚本。20-orbit 与 60-close 共用 |
| `scenes/05-light.js` / `light/` | 底层光影：三团颗粒渐变光体，各走各的连续轨迹，不读取任何场景对象；只按 SHIFT 表换算标志时刻——片头字标段压暗到每团 ≤ .15，片尾曲线画起前长淡到纯黑并保持到最后一帧 |
| `scenes/10-intro.js` … `60-close.js` | 各段（见上表），各自用 `scene(name, fn)` 注册；只写自己拍段的关键帧，交接约定见 STORYBOARD.md |
| `music.py` | 用 numpy/scipy 在同一拍网格上合成配乐（C 大调 / A 小调，vi–IV–I–V 循环），每个 cue 写在 `section('<场景>')` 里的场景拍，用同一张 `SHIFT` 表；输出 `out/soundtrack.wav` |
| `render.mjs` | 在 Playwright 的虚拟时钟上逐帧截图，再用 ffmpeg 与配乐合成 MP4 |

## 用法

```bash
uv run --with numpy --with scipy python promo/music.py
node build.mjs && node promo/render.mjs            # -> promo/out/orbit-promo.mp4
```

`render.mjs` 的参数：`--out <file.mp4>`、`--fps 60`、`--scale 2`（按 2× 渲染后缩放到 1080p）、`--from/--to <秒>`、`--frames <目录>`（输出 JPG 序列而不是 MP4）、`--only 16,20.5`（只截取这几个**成片拍**的画面，用于快速出联系表）、`--debug`。环境变量 `PROMO_PAGE=<文件名>` 可以渲染同目录下的另一个页面。

预览：在仓库根启动任意静态服务器，打开 `prototypes/advance/promo/promo.html`，点击「播放」即可带配乐实时播放（`?t=<秒>` 从中间开始，`?debug` 显示当前拍号）。实时预览的效果取决于机器性能，最终成片以 `render.mjs` 的输出为准。

## 拍号与 SHIFT

- 自 v17.3 起每个场景文件只用自己的拍号。`promo.js` 的 `SHIFT[场景]` 把该场景注册的一切——`tween` / `txt` / `tag` / `drive` / `at` / `clickAt` / `markAt` 与 AGD 的 `key` / `follow` / `pulse` / `link` / `bubble` / `glow` / `back` / `chat`——推后 SHIFT 拍。回调（`drive`、`markAt`、AGD 的活参数与目标）收到的仍是场景拍；回调运行期间 `CTX_SH` 保存它的 SHIFT，所以里面调用的 `AGD.pos(i, b)` / `AGD.centroid(b)` 也按场景拍读。
- 一个场景加长或收紧 N 拍时，只改自己的文件（起点和交接形状不变），之后各场景的 SHIFT 统一加 / 减 N；`promo.js` 与 `music.py` 是同一张表，两处一起改。10-intro 文件内另有 `T()`，把 v17.3 网格上的拍换算到插入读字时间后的场景拍。
- 片长：`60-close.js` 在自己的拍号里设 `END`（现为 `TURN0 + 13.0 = 94.8`），`script()` 加上设它的场景的 SHIFT（36.9）得 131.7 拍，`PROMO.duration = END × BEAT` ≈ 59.9 秒，须保持在 60 秒以内；`05-light.js` 每帧读引擎的 `END` 拉伸光路，`music.py` 的 `END` 须与之一致。
- `render.mjs --only` 与 `?debug` 显示的都是成片拍。

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头、文字、Agent 点、标志和字标都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。
