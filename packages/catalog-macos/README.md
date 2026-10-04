# OrbitCatalogClient

Swift 5.9+ 的异步 Catalog HTTP 客户端，Package 自身支持 macOS 13+；完整 Orbit App 的目标仍是 macOS 14+。Python Catalog 持有数据库、网络适配器与本地模型，客户端不在 UI 线程做采集或 SQLite 写入。

## 接入

在宿主的 Package Dependencies 中加入本目录并导入 `OrbitCatalogClient`。宿主负责启动后端、设置 loopback endpoint 和适用鉴权；默认客户端地址不应当作动态 App gateway 的实际端口。

```swift
import OrbitCatalogClient

let catalog = try CatalogClient()
let job = try await catalog.sync(sourceIDs: ["anthropic-skills"])
let completion = try await catalog.waitForJob(job.jobID)

var query = MatchRequest(text: "定位重复失败的根因")
query.types = ["skill", "workflow"]
query.agents = ["codex"]
let result = try await catalog.search(query)
```

示例假定默认 endpoint 上已有可访问服务。任务受理不等于完成，检查 completion 的状态、取消、错误与覆盖；仅取消 Swift 等待任务不会自动取消后端工作，使用相应 cancel API。

## 展示合同

结果同时显示分项分数、命中特征、来源片段和 vector 状态。资源检索与推荐模式不同：推荐还需要问题、场景、交付语言和证据。客户端不自动安装 Python、下载模型或创建系统服务。

验证：`python3 scripts/heavy.py swift test --package-path packages/catalog-macos`。接口与数据库职责见[目录架构](../../docs/modules/catalog/architecture.md)。
