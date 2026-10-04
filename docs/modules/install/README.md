# 资源安装与撤销

安装模块将推荐候选、目录资源或 AI 产物解析为统一 InstallSpec，生成目标环境中的具体修改，预览后确认应用。它与资源检索、AI 生成和会话数据导入各有独立边界。

## 状态流

| 步骤 | 输入与结果 | 是否修改 Agent 配置 |
| --- | --- | --- |
| resolve | 来源 → `ready` / `needs_fetch` / `link_only` 与规格 | 否；显式 fetch 可能写资源缓存 |
| plan | 规格 + agents/scope/project_path → 目标与操作 | 否 |
| preview | 选中单元、当前文件 → diff、风险、摘要 | 否 |
| apply | plan + 对应预览摘要 + 确认 | 是，写入并记录备份/账本 |
| revert | 安装 ID + 当前文件检查 | 按可撤销内容和冲突结果执行 |

入口为 [InstallService](../../../packages/backend/src/orbit_backend/install/service.py)。消费者不能把 plan 创建或 resolve ready 当成已安装，也不能绕过预览摘要执行与展示内容不同的修改。

## 目标与冲突

安装能力依赖 Agent、类型和作用域。未知环境、链接型资源、许可或获取限制应明确返回原因。应用前检查文件变化，撤销时检查安装后是否被用户或其他工具修改；备份不是无条件覆盖许可。

配置/库存观察和实际安装账本分别记录，reconcile 用于核对当前状态。安装成功不证明 Agent 已加载、调用或受益，效果追踪仍需要后续证据。

## 验证与扩展

用伪造 Agent home、构造资源和 FakeFetcher 覆盖解析、落点、预览、应用、重复调用、冲突、撤销和路径边界。不要在默认测试中修改真实 Agent 配置或执行资源脚本。

外部执行器的解析接口见[个性化产物契约](../../contracts/personalization-output.md)，用户操作见[推荐指南](../../guides/recommendations.md)。
