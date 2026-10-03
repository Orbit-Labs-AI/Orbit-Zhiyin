# 体验示例

Orbit 提供两种独立示例：浏览器里的界面演示，以及能生成真实分析产物的构造数据流程。两者都无需导入你的 Agent 历史。

## 浏览器界面

获取仓库后，用浏览器打开 [orbit-demo.html](../../prototypes/advance/orbit-demo.html)。文件已包含界面产物，可直接在侧栏顶部切换 Lite / Advance。此模式使用预设数据；人格、用量、推荐收益与实时活动都是示例，不能据此评价实际分析效果。

旧的 [Lite 独立原稿](../../prototypes/lite/orbit-benchmark-demo.html)保留设计来源；当前 App 使用 Advance 目录中的统一界面。查看[设计资料](../design/README.md)了解截图与素材的用途。

## 后端示例

先完成[开发环境](../development/setup.md)，再从仓库根运行：

```sh
uv run orbit demo
uv run orbit demo --view profile
```

默认结果写入 `.local/demo/`，示例数据 home 位于 `.local/demo/data/`。产物包括画像、瓶颈、推导过程和报告的 Markdown / JSON，可以检查结论引用了哪些构造证据。

```sh
pnpm dev --home .local/demo/data
```

该命令启动报告 API，在 [本机 API 文档](http://127.0.0.1:8765/docs)尝试读取项目、会话和分析。它不是 App gateway，不能据此假设 `/app` 已可访问；live UI 的启动方式见[开发环境](../development/setup.md#启动-app-gateway)。

## 下一步

准备好使用自己的记录后，按[导入指南](../guides/importing-data.md)显式选择来源，并使用独立 home 区分示例与真实数据。返回[开始使用](README.md)。
