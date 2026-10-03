# Orbit Codex Connector

TypeScript producer 将 Codex 本地轨迹写入独立 staging：归档、记录账本、标准事件和派生表。它使用 Node ≥24.7 的内置 SQLite/zstd，不引入原生扩展，也不调用模型或上传会话。

## 从根 workspace 运行

```sh
bash scripts/bootstrap.sh
pnpm --filter @orbit/connectors build
node packages/connectors/dist/cli.js --help
node packages/connectors/dist/cli.js discover --codex-home /absolute/authorized-codex-home
node packages/connectors/dist/cli.js ingest --codex-home /absolute/authorized-codex-home --data-dir /absolute/codex-staging
```

discover 只发现，ingest 显式启用来源；watch 用于持续读取已选择来源。省略来源参数时 CLI 读取 `CODEX_HOME` 或默认目录，因此自动化中应显式传参。默认 staging 位于 Orbit home 下的 `connectors/codex`，不能与 canonical 库混用。

## 采集合同

来源保持只读，输出不得位于来源内，路径按真实位置校验。归档记录代次、分块大小与哈希，L1 保留每条记录的处理去向。未知类型、部分尾行、损坏记录与调用状态缺失不能通过跳过或补成功隐藏。

原生会话、轮次、call ID 与事件语义路径决定身份，时钟不可靠时仍保留原生顺序。累计用量与逐次请求分开，调用配对限定在相应线程/轮次，正文镜像不重复计数。字段以 [schema](schema/) 和实现为准。

## 接入 Orbit

```sh
uv run orbit --home /absolute/orbit-home import-connector --connector-home /absolute/codex-staging
```

桥接只读 staging 归档、验证哈希，并通过 Python mapper 重建 canonical L2/L3。不能直接把 staging 数据库交给分析模块，两个生产者也不能共写一个文件；详见[数据契约](../../docs/contracts/data.md)。

## 验证

```sh
pnpm --filter @orbit/connectors check
```

检查包含 typecheck、构造样本回归与 build。跨语言桥接在根集成测试中验证，producer 必须先构建。真实日志、原始归档和派生库只放本地忽略目录；测试只提交构造或充分脱敏样本。
