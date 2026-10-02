# UI 原型

当前两套原型都使用示例数据，与生产数据入口分别运行：

| 原型 | 设计归属 | 入口 | 检查 |
| --- | --- | --- | --- |
| Lite | genius-FXC | [单文件 HTML](lite/tandem-benchmark-demo.html) | pnpm --filter @tandem/prototype-lite check |
| Advance | yhyfhgs | [单文件 HTML](advance/tandem-demo.html)、[源码](advance/src/) | pnpm check:ui |

Advance 的 HTML 是生成产物，编辑 src 后执行 `pnpm --filter @tandem/prototype-advance build`。Lite 保留原有独立 HTML 编辑方式。构建顺序、内容和交互保持原设计行为。

设计规范与画板位于 [docs/design](../docs/design/README.md)。正式 macOS UI 接入未来的 apps/desktop；原型通过不代表真实数据接入或安装包已完成。
