# 个性化产物解析契约

App 和外部评测执行器共用推荐、AI 生成和安装解析模块。执行器消费已经解析的产物，不建立第二套召回、模板或 Catalog 内容。

## 从推荐到规格

1. 在独立 home 中导入获准历史，按目标范围请求 App 推荐并等待相应结果就绪。
2. 对普通候选保留 `candidate_id`、run、证据和被过滤原因；`rec_key` 不能替代候选 ID。
3. 调用 `POST /v1/install/resolve`。`kind=generate` 先经过现有 AI 预览、任务和产物流程，再用 artifact 来源解析。
4. 只有 `status=ready` 的 payload 可转换为执行器格式。待获取、仅链接、不支持或生成失败必须保留原因；空结果记为 abstain。

## 请求与状态

```json
{
  "source": {"type": "candidate", "id": "candidate_id"},
  "fetch": false
}
```

`source.type` 支持 `candidate`、`catalog`、`artifact` 的 ID，或携带现有 `spec` 对象的 `spec`；宿主汇总流程的 `collect` 不适用于该接口。`fetch` 默认 false，显式开启后沿用安装模块的来源获取和缓存。

响应返回原 InstallSpec 与解析器状态，不另造 benchmark 专用格式：

| status | 消费规则 |
| --- | --- |
| `ready` | 规格已物化，可检查 payload 是否被执行器支持 |
| `needs_fetch` | 尚需资源获取，不作为已注入 |
| `link_only` | 保留链接与原因，不假装存在可执行正文 |

## payload

| kind | 主要内容 | 适配边界 |
| --- | --- | --- |
| rule | `text` | 保留来源与作用域 |
| skill | `name`、`files[].rel/text` | 正文和辅助文件共同处理 |
| hook | `event_bindings` 或 `event`/`command`，可含脚本与辅助文件 | 事件、路径占位符与执行器运行时显式映射 |
| 其他 | 原 InstallSpec | 执行器明确判断支持范围，不静默丢弃 |

ready 只证明解析成功，不证明目标 Agent 实际加载、调用或执行成功。记录实际注入内容与摘要，实验需要干预时在正式执行前检查是否有可用产物。

## 副作用与错误

resolve 不创建安装计划，不写 Agent 配置或安装账本，不执行脚本；`fetch=true` 可能写资源缓存。真正安装继续走 `plan → preview → apply`，共用同一个 `build_spec`。

接口继承 gateway 鉴权、Host/Origin 与错误结构。调用方同时检查 HTTP 状态和 body.status；404 表示缺少来源对象，422 表示规格或候选不合法，获取/许可错误沿用安装模块。实现见 [routes_install.py](../../packages/backend/src/orbit_backend/services/routes_install.py) 与 [InstallService](../../packages/backend/src/orbit_backend/install/service.py)。

使用构造日志、伪造 home 和 FakeFetcher 验证 resolve/plan 内容一致性及失败路径。未来效用评测见[Benchmark](../../evals/benchmark/README.md)。
