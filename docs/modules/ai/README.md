# AI 模块

AI 为已有事实增加按需解读、问答、分类与生成。普通统计分析不依赖模型；模型输出不能直接写成 canonical 事实、用户授权或客观验收。

## 调用链

`preview → consent / budget → job → runner → schema / evidence validation → artifact / narrative`。入口在 [ai/service.py](../../../packages/backend/src/orbit_backend/ai/service.py)，App 路由由 services 提供。任务定义、引擎能力、上下文构建、运行隔离和产物分别维护。

默认 `mode=stats`，自动新会话处理关闭。授权按引擎和数据类别记录，结构化统计、脱敏片段和规则段落分别授予；`raw` 不允许发往引擎。引擎出现在配置中不代表可用，调用前读取能力和错误状态。

## 上下文与输出

上下文先应用项目、来源、时间、会话和排除范围，再选择必要证据并限制预算。缓存身份包含输入和任务版本；历史材料或范围变化后不能复用旧解释。令牌、成本和时间预算分别说明，不能将本地输出限制写成服务端硬保证。

结构校验要求固定字段和可回查引用；输出中的建议、推断和局限分别保留。失败、取消、引擎不可用和授权不足不得产生假完成产物。自动任务也受授权约束，开关与授权撤销各自生效。

## 两类语义路径

App AI service 处理用户可见任务。analytics 的 [semantic_cascade](../../../packages/backend/src/orbit_backend/analytics/semantic_cascade/README.md) 是独立的显式语义观察流程，有自己的选择、预算、缓存和证据规则；不能把其存在解释成普通分析会自动外发文本。

## 生成与安装

生成工坊产出可审阅的规则、Skill、Hook 等草稿，经过格式/内容检查后才交给[安装流程](../install/README.md)。自检通过不等于安全审计或实际有效，自动生成也不自动授权写用户配置。

本地 Agent 仍可能调用其配置的远端模型。用户说明见[使用 AI](../../guides/ai.md)，验证记录见[AI 可靠性审计](../../audits/analysis-ai-reliability-2026-10-03.md)。

