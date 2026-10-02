# TandemCatalogClient

供 macOS 13+ App 使用的 Swift Package。Python `tandem_catalog` 拥有数据库、网络连接器与本地模型；本包通过 loopback HTTP 提供异步调用，不在 UI 线程执行采集、推理或 SQLite 写入。

在 App 的 Package Dependencies 中加入本目录，导入 `TandemCatalogClient`。宿主 App 负责启动或连接本地 Python worker，并将固定版本的模型目录传给 worker；本包不会自动安装 Python、下载模型或创建 launchd 任务。

```swift
import TandemCatalogClient

let catalog = try CatalogClient()
let job = try await catalog.sync(sourceIDs: ["anthropic-skills"])
let completion = try await catalog.waitForJob(job.jobID)
// completion.status / result 包括失败、取消和分页预算耗尽；不能只看请求已受理。

var query = MatchRequest(text: "定位重复失败的根因")
query.types = ["skill", "workflow"]
query.agents = ["codex"]
query.features = [Feature("domain", "debugging")]
let result = try await catalog.search(query)
// A8 使用 result.items；显示 scoreParts / matchedFeatures / passage 和 vector 覆盖状态。
// A7 还须设置 purpose="recommendation"，并传入 problem、scene、language 与两组证据 ID。
```

`sync()` 可以由 App 的启动、唤醒或定期刷新调用，后端会检查各来源的下一次更新时间。`indexPendingChunks()` 分批补齐向量；中止或重启后可继续。`cancel(jobID:)` 在当前读取页/推理批次结束后暂停任务；取消等待的 Swift Task 本身不会修改 worker。

完整架构、命令和接口见 [`docs/modules/catalog/architecture.md`](../../docs/modules/catalog/architecture.md)。测试：`swift test --package-path packages/catalog-macos`。
