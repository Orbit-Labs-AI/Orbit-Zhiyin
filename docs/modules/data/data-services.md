# 本地数据服务

导入之外，`orbit_data` 提供搜索、继续会话命令、来源能力、空间统计、脱敏预览和受控清理。大多数服务读取已发布事实；显式清理、缓存或用户给定的 insights 路径各有额外边界。

| 服务 | 实现 | 入口 |
| --- | --- | --- |
| 搜索 | `search.py` | `orbit-data search`、`/v1/search` |
| 继续命令 | `resume.py` | `orbit-data resume`、会话 resume 接口 |
| 来源能力 | `capabilities.py` | `orbit-data capabilities`、sources capabilities 接口 |
| 空间与清理 | `maintenance.py` | `storage`、显式 `purge` |
| 脱敏预览 | `privacy_rules.py` | `privacy-rules`、`privacy-preview` |
| insights 对照 | `insights.py` | 显式 `insights --path`，不自动找个人目录 |

## 搜索与继续会话

搜索覆盖适用的消息/标题、项目、命令头与文件信息；FTS 能力不足或短查询可走受限回退。返回类型、身份、片段、范围与截断说明，工具输出不无条件全文索引。

resume 生成参数和可展示命令，不执行它。只在有支持的主会话身份、cwd/文件等条件时给出可用结果；活动会话、子代理或缺身份保留原因。模板基于已研究上游，不能保证任意新版本 CLI 都兼容。

## 能力与库存

静态能力矩阵、实际观察的事件和安装配置是三种证据。声明支持 Hook 不证明本机已经使用；缓存配置不等于实时安装状态。来源和 inventory 版本变化应使相应缓存失效。

## 空间和清理

空间统计区分数据表、索引、空闲页、WAL 和 raw；冷库遍历可能耗时，前端异步展示。底层 `purge_all` 使用固定确认词、路径/符号链接和导入锁检查，仅处理其声明的会话库、raw 及相关缓存，不等于删除 `catalog.db`、所有 App 数据或 Agent 来源。

应用层清理应通过对应生命周期重开连接，不能在活跃连接继续使用已删除文件。用户对删除范围的确认与暂停、排除操作分开，见[隐私指南](../../guides/privacy.md)。

## 脱敏与 insights

预览复用当前脱敏规则，不持久化输入；规则命中不保证完全匿名。insights 只读用户明确给出的目录，限制文件大小与形态，损坏输入记录错误代码。外部报告字段不作为 canonical 真值，不从其完整度反推来源完整度。

路由见 [api/data_routes.py](../../../packages/backend/src/orbit_backend/api/data_routes.py)，用户命令见[CLI](../../development/usage.md)。

## 搜索排序说明

消息检索涵盖真人/助手消息与标题，不以摘要或工具输出补齐全文。相关度乘类型权重和时间衰减；未知时间取最低保底，不优于同类有时间命中。权重、半衰期与保底是产品默认，手写偏好回归不等于实际点击校准。
