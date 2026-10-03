# 画板与实现的关系

`visual-cases-v1` 保留 Advance 早期视觉画板，部分资产随后曾更新。画板用于追溯设计，不是当前字段、页面和能力的完整合同。当前可运行界面在 [prototypes/advance](../../prototypes/README.md)。

## 画板索引

文件均在 [visual-cases-v1](visual-cases-v1/)：

| 页面 | 画板 | 文件 | 内容 |
| --- | --- | --- | --- |
| 主应用 | A1 概览 | `Main.dc.html` | AI 解读、指标卡、Agent 使用趋势、人格迷你卡、活跃节律、工具 Top、本周建议 |
| 主应用 | A2 协作人格 | `Persona.dc.html` | 类型代号 DIMV、协作指纹、四个维度、优势与盲点、Agent 契合度、演变 |
| 主应用 | A3 会话轨迹 | `Sessions.dc.html` | 会话列表、泳道时间轴、播放头、关键时刻、会话启示 |
| 主应用 | A4 工具调用 | `Tools.dc.html` | 工具明细表、调用链矩阵、失败原因、审批负担、MCP 与子代理 |
| 主应用 | A5 项目习惯 | `Projects.dc.html` | 项目表、跨项目对比散点、项目与整体对比、识别到的工作流、规则覆盖 |
| 主应用 | A6 情绪语义 | `Sentiment.dc.html` | 情绪曲线、摩擦分类、语义主题、高频反馈语、情绪前因 |
| 主应用 | A7 优化建议 | `Recs.dc.html` | 七个维度、L1–L4 难度、按用户水平筛选、依据、收益、预览与安装 |
| 主应用 | A8 资源库 | `Library.dc.html` | 按人格精选、匹配度拆解、相似用户 |
| 主应用 | A9 生成工坊 | `Studio.dc.html` | 上下文包、本地 Agent 执行、分步流程、流式预览、自检 |
| 主应用 | A10 设置 | `Settings.dc.html` | 数据源、索引方式、分析引擎、脱敏规则、数据存储 |
| 人格系统 | P1 16 型图谱 | `TypeMap.dc.html` | 四个维度的定义、信号与计算方法，16 种类型 |
| 人格系统 | P2 分享卡 | `ShareCard.dc.html` | 1080×1350 分享图（深色，可切浅色）；2026-10-03 起由 `prototypes/advance/tools/share-board.mjs` 从 App 的 `shareSVG()` 生成：Orbit·知音 字标、时间长度标签与日历环、SF Pro Rounded 类型码、16 型新版名称与描述 |
| 人格系统 | P3 揭晓动效 | `Reveal.dc.html` | 3 秒动效分镜与减弱动态效果方案 |
| 菜单栏 · 悬浮 · 小组件 | B1 桌面全景 | `Desktop.dc.html` | 菜单栏、面板、悬浮胶囊、小组件同屏 |
| 菜单栏 · 悬浮 · 小组件 | B2 菜单栏面板 | `MenuBar.dc.html` | 运行中、空闲、需要关注三态，状态图标 |
| 菜单栏 · 悬浮 · 小组件 | B3 悬浮组件 | `FloatHUD.dc.html` | 五种收起态、展开态、吸附与隐身规则 |
| 菜单栏 · 悬浮 · 小组件 | B4 桌面小组件 | `Widgets.dc.html` | 小、中、大三种尺寸，全彩与着色 |
| 菜单栏 · 悬浮 · 小组件 | B5 系统通知 | `Notify.dc.html` | 通知分级与投递矩阵 |
| 关键流程 | C1 首次启动 | `Onboarding.dc.html` | 四步引导 |
| 关键流程 | C2 安装闭环 | `InstallFlow.dc.html` | 建议、预览、确认、撤销、7 天效果追踪 |
| 关键流程 | C3 生成工作流 | `GenFlow.dc.html` | 本地 Agent 生成流程与数据边界 |
| 关键流程 | C4 状态规范 | `States.dc.html` | 8 种空、加载、异常状态 |
| 关键流程 | C5 键盘 · 动效 · 无障碍 | `Interaction.dc.html` | 命令面板、快捷键、动效令牌、无障碍要求 |
| 设计语言 | D1 设计令牌 | `Tokens.dc.html` | 颜色、字体、间距、圆角、层级 |
| 设计语言 | D2 组件 | `Components.dc.html` | 按钮、选择控件、标签、卡片、会话行、步骤等 |
| 设计语言 | D3 侧边栏组件 | `Sidebar.dc.html` | 被 A1–A9 引用的侧边栏 |

## 使用次序

实现行为以源码、测试和[展示指标](../modules/analytics/presentation-metrics.md)为准，名称/图标以[品牌](brand.md)为准，人格素材以[当前导出](persona/README.md)为准。历史样例数字不作为计算公式或产品收益。

新的设计决定同时说明影响的版本、页面、数据合同与状态处理；不要只改画板文字而遗漏源码与生成产物。设计演变见[历史记录](../archive/design/design-history.md)。
