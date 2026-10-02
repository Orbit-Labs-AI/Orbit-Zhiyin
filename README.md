# Hackathon

ActionMesh AI 团队的 Hackathon 比赛项目。

## 状态

- 仓库初始化：2026-09-30
- 赛题、技术栈与分工：待定
- 设计参考：[docs/design](docs/design/README.md)（Tandem 视觉案例 v1，MVP 范围待三人确认）
- Codex 数据连接器：[packages/connectors](packages/connectors/README.md)（本地归档、标准化事件、SQLite 派生表与 CLI）

## 快速开始

Codex 数据连接器使用 TypeScript、Node ≥24.7 与 pnpm：

```sh
cd packages/connectors
pnpm install --frozen-lockfile
pnpm check
pnpm tandem --help
```

完整使用方法、数据契约和构造样本演示见 [Connector README](packages/connectors/README.md)。
