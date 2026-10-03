# Orbit 宣传片

约 60 秒（131.7 拍，132 BPM，1 拍 = 0.4545 秒，成片 ≈ 59.86 秒）、纯黑背景的 Orbit 产品宣传片（v18.5）。每轮打磨改了什么见 [STORYBOARD.md](STORYBOARD.md) 开头的「打磨记录（v18）」，点的形态见「v17.7」一节，现状与逐段关键拍见「现状」一节（再往后各节是历史记录），参考片的动效总结见 [REFERENCES.md](REFERENCES.md)。拍号以 `scenes/*.js` 为准。

全片只有一套 Agent 点：5 个 Agent 的圆形标志（`agBadge`，即 App 的 `agLogo`）从第一拍弹出，始终是一个紧凑的小组、也就是视线中心，一路变换编队，把各段连成一条线：簇 → 笔尖（∪ 弧）→ 窄弧 → 光标 → 窄弧 → R 420 圆环 → 标志外的倾斜轨道 → 字标下一行 → 罗盘外圈（随 Agent 曲线公转）→ 左侧短列 → 合并为一（骑播放头、当光标、当生成源）→ 螺旋放出成环 → 罗盘 → 圆环 → 笔头后的一串 → 图标下一行 → 标语下一小行。自 v17.7 起点还会变形（`AGD.morph`，12 种形态：dot caret pill tail bead petal bullet pin pointer spark head orb），每次变形都配一个画面元素，凡是点状形态 logo 都保持可认。另外几样由宣传片自己绘制：

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
| `40-recs.js` | 22.9 | 39.4–63.8（剥离自 38.5） | 62.3–86.7 | 28.3–39.4 | % 结论完整停到场景 b63.4（成片 86.3），b63.4–63.85 朝合并点漂移淡出；b63.2 起点列向合并点 (330, 540) 收拢，b63.6（成片 86.5）收成一个 orb |
| `50-tools.js` | 31.7 | 55.0–75.2 | 86.7–106.9 | 39.4–48.6 | 场景 b55.2 起轨迹卡以 orb 为原点长出；场景 b73.9–74.35 SKILL.md 以 E.in 缩到 .12 平移进 orb（只在最后 .15 拍淡出），orb 同时走向画面中心并 1 → 1.5 放大加 glow，b75.2（成片 106.9）以大 orb 到位 |
| `60-close.js` | 37.7 | 69.2–94.0 | 106.9–131.7 | 48.6–59.86 | `TURN0 = 80.4`，`END = 94.0` 与 `FADE0 = 92.2` 写死（场景拍）→ 片长 131.7 拍 |

## 时间轴

| 段 | 文件 | 成片拍 | 秒 | 内容 | Agent 点 |
| --- | --- | --- | --- | --- | --- |
| 1a | `10-intro.js` | 0–6.6 | 0–3.0 | 小字「AI Agent，」/ 大字「正在成为每个人的日常」逐词落定，「日常」橙色盖章（b2.6） | orb 弹出拆成五点 → ∪ 笔尖（领头 pill 推词）→「日常」盖章压扁 |
| 1b | `10-intro.js` | 6.6–13.2 | 3.0–6.0 | 原地匹配剪辑：b6.95 起「从想法到交付」在旧标题中线 y 540 擦出、与旧行模糊淡出叠化（每帧都有标题），b7.35–8.1 标题与点列一起抬到终位；输入框从点里长出、三次发送、各家 prompt 气泡；12 个 App 图标迸到光环（b11.35） | ∩ 窄弧 → cx 长 pill 的细 stem 尖端贴「从」左下角（b6.95）→ pill 拉出输入框 → 打字 caret、气泡 tail → b11.15 spark → pill 收进框 |
| 1c | `10-intro.js` | 13.2–19.65 | 6.0–8.9 | 「We Are Redesigning Everything」逐词（We b13.65 起擦，Are 14.3 · Redesigning 14.8 · Everything 15.3；整行按最终居中宽度排好，未出现的词用 visibility 隐藏、由左向右擦出，已落下的词不再左滑），下方「人们正在用 Agent 重新设计一切」（随主标题退场，b19.2 淡完）；图标被吸近、转向、飞出 | 五点 b12.95–13.75 用 .8 拍左移，b13.75 成形的 caret 即骑在擦出前沿滑行（与擦出同为 .24 拍 E.out），不独处→ 收拢成五色分段光标 |
| 1d | `15-redesign.js` | 18.7–27.6 | 8.5–12.5 | 「但，」（52 px / 600 银色，b19.25 起在点列上方 blurIn 后上升，b19.75 落定、单停约 .3 拍）/「人与 Agent 的交互本身，」（荧光笔）/「也需要被重新定义」；纠正指令气泡越来越密 | 光标倒下滚成点 → pill 拉出输入框 → caret、tail → 荧光笔 head |
| 1e | `15-redesign.js` | 27.2–34.3 | 12.4–15.6 | 「So，」在环心叠入 1d 退场，b27.8–28.4 用 .6 拍 E.inOut 升到行位 →「我们做了一个 Assistant」（52 px / 600，Assistant 60 px 纯白；整行单独停留约 .7 拍）→ 环内三行硬切 Redesign / Agent Workflow / for everyone（b29.4 / 29.8 / 30.2，约 92 px，开场最大字），随后环与标题慢推 1 → 1.04 | pill 收回 → 圆环 bead，虚线圆从珠子画出，三行硬切时前跳，glow |
| 2 | `20-orbit.js` | 32.9–45.1 | 15.0–20.5 | 圆环收紧 → 俯视螺旋 → 立成 45° 标志 → kit 转身成「Orbit·知音」（b35.9–39.9）+「你的 AI 协作复盘助手」（b38.0）→ 收字、O 转回 → 翻平交给罗盘 | 轨道 bead 收紧 → 字标下一行 bead → dot（字母升起时行发光）→ 回轨 bead → 罗盘 dot + 顺时针 glow |
| 3 | `30-persona.js` | 43.3–62.3 | 19.7–28.3 | 01 协作人格：罗盘成形、花落在 SIFT；左移后右列滚动分析，花一瓣瓣换成 DIFT → DIMT → DIMV（落定 b58.6），揭晓时问题行与字母牌淡到 0 | 五点全程在罗盘外圈公转；petal 合拢 / 张开，三次换花 petal 顺时针扫过，揭晓 ring 由内向外 |
| 4 | `40-recs.js` | 61.4–86.7 | 27.9–39.4 | 徽章按行剥离成左列，前三行各连出引言卡一行「02 · 优化建议 / 每条建议，都来自你自己的会话 / 提高效率」；6 条建议卡放大滚动（正文约 30 px，b68.9 起每 2.6 拍一条），「累计可节省的协作时间」/「累计可节省的 Token」两个计数器（b67.9 一起擦入，每次滚动随该卡 ✓ 起跑，总数始终等于已过卡片之和）；b82.5 起居中 % 结论：橙色「提高效率」独占一行 + 银色数字 + 36 px 标签「可节省的协作时间」「可节省的 Token」+ 28 px 说明，完整可读 b83.15–86.3，朝合并点漂移退场 | 左侧短列：前三行 pill 出线、两行 bullet → 三次呼吸 → 每条 pill 送出 + ✓ tick → 收圆 |
| 5 | `50-tools.js` | 86.7–106.9 | 39.4–48.6 | 收成一个 orb（b86.5）→ 会话轨迹卡以 orb 为原点 .12 → 1 长出（b86.9 起，.8 拍），眉标「03 · 会话轨迹」，只取时间线（约 1300 px 宽，正文约 22 px，走过的阶段压暗 .45）（阶段标注在卡顶上方、实色缩放入场）→ b98.3–98.85 orb 移到 (1180, 700)，轨迹卡在此缩进 orb，「开始生成」从该点长到 (960, 690)，04 眉标 b99.3 前清晰 → 推近到「开始生成」约 2.5 倍，b100.2 hover、b100.5 按下（缩 .94 回弹 + 橙色环），滑到单独的 SKILL.md；b104.3 徽标换绿色「已写入 ✓」、骨架条收起、第 1–8 行压到 .55，第 9 行被 orb 点亮 | 合并 orb（不再交叉淡成小徽章）→ pill 出线 → 骑播放头的 pin（各阶段钉入，失败段转暖）→ pointer 按下「开始生成」→ spark 生成源 → pin 停第 9 行旁 → SKILL.md 被吸入 orb，orb 1 → 1.5 加 glow 走向中心 |
| 6 | `60-close.js` | 106.9–118.1 | 48.6–53.7 | 螺旋放出成环 → 罗盘 → 收回圆环 → 曲线一笔画出（b113.3–116.3）→ 转身倒成 45° 图标，停留中慢推 1 → 1.04，b118.3 起即转身（E.sine） | 完整 orb 直接弹开成 5 枚可认 logo 的点（r ≈ 14，不再先缩成小团）成 head 彗星 → 罗盘 petal 合拢 + glow 扫过 → bead 收回 → 笔串（领头 head）→ 落行 dot r 22、±3 px 波 |
| 7 | `60-close.js` | 118.1–131.7 | 53.7–59.86 | kit reveal 成「Orbit·知音」→「Redesigning Agent Workflow for everyone & every agent」（b122.1，可读到 b129.9）→ b129.9 起淡到全黑 | 字母升起时点波 → 标语行 r 16 逐词点亮 → bullet + ✓（徽章步距 68，✓ 不碰相邻徽章）→ 合成 orb 淡出 |

## 文件

| 文件 | 作用 |
| --- | --- |
| `promo.html` / `promo.css` | 1920×1080 舞台：`#app0`/`#app1` 两份 App 与 `#cam2` 罗盘，各有一组 `.cam`/`.rig` 镜头；`#orbit` 画标志；`#fx` 放文字；按文件名顺序加载 `scenes/*.js` |
| `promo.js` | 引擎（以拍为单位，132 BPM）：`SHIFT` 表与 `END`、`shot()`/`tween()` 镜头、`txt()`/`tag()` 文字、`drive()`/`every()` 逐帧驱动、`clickAt()` 点击 bloom、`drawCompass()` 罗盘、`markAt()`/`markRing()`/`MARK` 标志姿态、`stageXY()`/`elXY()` 屏幕坐标、虚拟时钟 |
| `scenes/00-kit.js` | 共用的文字形式（`K.words`、`K.big`、`K.swap`、`K.blurIn`、`K.centerOut`、`K.decode`、`K.mark` 等）与 `hash01` |
| `scenes/02-agents.js` | Agent 点层 AGD：`AGD.key(b, form, o)` 编队关键帧（ring / arc / column / orbit / compass / merge / row …）、`AGD.follow`、`AGD.chat` 输入框、`AGD.bubble` 气泡、`AGD.link` 连线、`AGD.pulse`、`AGD.glow`、`AGD.back` 点下方的绘制层、`AGD.pos` / `AGD.centroid` |
| `scenes/03-wordmark.js` | 字标展开 helper（不注册场景）：`WORDMARK.place(pose)` 把 kit 第 0 帧对齐到 `orbitSVG` 的 ICON 姿态，`WORDMARK.svg(o)` 按转身进度 `v`、字母起落拍与 `offRate` / `color` 画进它自己插在 `#orbit` 之上的 `#wordmark` 层；帧加载完才启动脚本。20-orbit 与 60-close 共用 |
| `scenes/05-light.js` / `light/` | 底层光影：三团颗粒渐变光体，各走各的连续轨迹，不读取任何场景对象；自 v18.1 起路点直接写成片拍（不再按 END 拉伸），1e 起 ring 光是外缘也渐隐的环带、圈住 R 420 点环与人格表盘（v18.2），强度按章节做明暗弧线，`.light` 带静态边缘衰减让画面往中心收，`PAR` 视差表随前景移动、`DS` 尺度视差随推镜缩放（v18.4）；片头字标段压暗到每团 ≤ .15，片尾曲线画起前长淡到纯黑并保持到最后一帧 |
| `scenes/10-intro.js` … `60-close.js` | 各段（见上表），各自用 `scene(name, fn)` 注册；只写自己拍段的关键帧，交接约定见 STORYBOARD.md |
| `music.py` | 用 numpy/scipy 在同一拍网格上合成配乐（C 大调 / A 小调，vi–IV–I–V 循环；1b/1d 逐字按键声，点变形在独立 morph 总线上低于主 cue ≥ 10 dB），每个 cue 写在 `section('<场景>')` 里的场景拍，用同一张 `SHIFT` 表；输出 `out/soundtrack.wav` |
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
- 片长：`60-close.js` 在自己的拍号里设 `END`（v18.5 起写死为 94.0，`TURN0 = 80.4`、`FADE0 = 92.2`），`script()` 加上设它的场景的 SHIFT（37.7）得 131.7 拍，`PROMO.duration = END × BEAT` ≈ 59.86 秒，须保持在 60 秒以内；`05-light.js` 的路点是固定成片拍，只有末尾淡出 [END − 3.6, END] 读引擎的 `END`，`music.py` 的 `END` 须与之一致。
- `render.mjs --only` 与 `?debug` 显示的都是成片拍。

每一帧先把时钟推进整数毫秒，再执行 `PROMO.sync(t)`：所有镜头、文字、Agent 点、标志和字标都只由 `t` 计算；App 里正在进行的 CSS 动画和过渡也会暂停，并把进度设到同一时刻；JS 定时器和 `requestAnimationFrame` 则由 Playwright 的假时钟驱动。因此无论机器快慢，画面都会准确落在拍子上。View Transition 不受虚拟时钟控制，所以渲染时会关闭，改走 App 自带的回退动画。

成片、帧序列与 `out/` 都不进仓库。
