# Orbit 宣传片工程

本目录包含宣传片的舞台、场景、配乐和逐帧渲染工具。[分镜](STORYBOARD.md)与[参考研究](REFERENCES.md)记录对应版本的创作依据。片中的人格、收益和“7 天后”均为演示叙事，不是实际用户试验或收益承诺。

## 资产与版本

场景从 `../orbit-demo.html` 提取组件，另有片内罗盘和标志绘制。该片的旧指南针罗盘与当前 App 人格之花不同；更新宣传物前需按[设计规范](../../../docs/design/README.md)核对，不把旧镜头当作当前界面。

`promo.html`/`promo.css` 管舞台，`promo.js` 管镜头与时钟，`scenes/` 管分段，`music.py` 生成配乐，`render.mjs` 通过 Playwright 和 ffmpeg 输出视频。当前分镜的时长与拍号属于版本化设计，修改场景时同步对应说明。

## 运行

先准备仓库依赖、Playwright Chromium 和 ffmpeg。从 `prototypes/advance` 执行：

```sh
uv run --with numpy --with scipy python promo/music.py
node build.mjs
node promo/render.mjs
```

全片渲染是重负载，从根工作区调度时使用 `scripts/heavy.py`。渲染支持 fps、scale、from/to、frames、only 和 debug 等选项，以脚本 `--help` 或参数定义为准。静态预览打开 `promo.html`，最终时间轴以虚拟时钟逐帧输出为准。

视频、音频与帧序列写入忽略的 `out/`，不提交大型生成物。引用任何节省百分比时明确标成示例，发布前同步现行 UI、许可与产品边界。
