# 个性化产物输出接口

状态：已实现。Orbit 的 App 和外部执行器共用推荐、生成及安装解析模块；benchmark 不另做召回、gate、KB 模板或 Catalog 引用解析。

## 复用的调用链

1. 使用 App 既有来源导入与分析接口，在独立 Orbit home 中只导入获准的 history。
2. 调用 `GET /v1/recommendations?surface=A7&include_gated=true&wait_ms=3000`。等待 `meta.freshness=fresh`，保留 `run`、`problems`、`items`、`gated` 和各候选原因。App 在启动时离线初始化产品 Catalog；无需导入个人 Catalog。
3. 对选中的普通候选，将返回的 **candidate_id**（不是 rec_key）交给下述 `/v1/install/resolve`。同 App 安装流程一样，它解析内置模板、KB 的 `catalog_ref` 和 Catalog 文件。
4. `kind=generate` 是生成占位，不是已生成 Skill。通过现有 `/v1/ai/preview`、`/v1/ai/jobs` 和 `/v1/ai/artifacts` 完成产品生成，再用 `source.type=artifact` 解析产物。生成的授权、引擎配置、失败状态沿用 AI 接口。
5. 执行器仅将 `status=ready` 的 `InstallSpec.payload` 转换成自身的注入格式；完整保留未选中、待获取、不可物化、生成失败和不支持的原因。

该接口不修改推荐、自动生成或自动安装。若全部资产为空，调用方必须将其明确记为 abstain；若实验要求实际 layer 干预，应在付费 test 开始前停止。原始 `no_matching`、空列表或待获取状态不能改写成“已成功注入”。

## POST /v1/install/resolve

复用 [InstallService.resolve](../../packages/backend/src/orbit_backend/install/service.py) 和现有 [build_spec](../../packages/backend/src/orbit_backend/install/plan.py)，路由位于 [routes_install.py](../../packages/backend/src/orbit_backend/services/routes_install.py)。鉴权、请求来源检查与错误封装沿用 Gateway。

请求：

```json
{
  "source": {"type": "candidate", "id": "推荐接口返回的 candidate_id"},
  "fetch": false
}
```

`source` 使用已有形式：`candidate`、`catalog`、`artifact` 携带对应 `id`；`spec` 携带原有 `spec` 对象。`collect` 是宿主安装汇总流程，不适用于此解析接口。`fetch` 默认 false；明确为 true 时允许原安装模块获取远程资源，其缓存与来源信息仍由同一模块管理。

响应保留原解析器的 `extra` 状态和原始 `InstallSpec`，不新增 benchmark 专用产物格式：

```json
{
  "status": "ready",
  "spec": {
    "kind": "rule",
    "id": "example-rule",
    "title": "Example rule",
    "scope": "user",
    "payload": {"text": "Inspect inputs before editing."},
    "source": {"type": "candidate", "id": "candidate_id"}
  }
}
```

上例省略 `InstallSpec` 的其他已有字段。`status` 与原解析器一致：`ready`、`needs_fetch`、`link_only`；有资源获取信息时，原 `fetch` 字段一并返回。只有 `ready` 的 payload 可供执行器注入；非 ready 响应中的 spec 只是尚未完成物化的描述。

| 现有 kind | 可供执行器使用的现有 payload |
| --- | --- |
| rule | `text` |
| skill | `name`、`files[].rel/text`，包含 Skill 正文及辅助文件 |
| hook | `event_bindings` 或 `event`、`command`，内置脚本还包括 `script.name/text` 和 `extra_files` |
| 其他 kind | 保留原 InstallSpec；由执行器明确判断支持范围，不静默丢弃 |

Hook 的事件与路径占位符仍属于安装规格，外部执行器应按自己的运行时映射；`ready` 只表示产品解析成功，不代表 Pi 或其他执行器已经执行成功。Skill 是否实际被 agent 读取也应另行记录。

此接口不解析宿主 agent 落点、不创建 install plan、不写 agent 配置或安装账本、不执行脚本。`fetch=true` 可能写资源缓存。需在宿主实际安装时仍使用原 `plans → preview → apply` 流程；同一来源的 resolve 与 plan 使用同一个 `build_spec`，不会产生两套资源内容。plan 会额外应用调用方指定的 agents、scope、project_path，并解析具体安装位置。

错误仍为 `{"error":{"code":...,"message":...}}`：缺少候选/产物为 404，规格不合法或候选槽位未填完为 422，资源获取与许可证条件沿用原安装模块。调用方应检查 HTTP 状态和 body.status 两层结果。

## 修复后的推荐输入

- 复合 shell 调用按明确的 shell 诊断识别实际缺失程序；不能确定归属时不硬归到第一条命令。读取文件内容不会作为 shell 错误证据。命令头无法完整计量的程序不再使用偏小的软件分母。
- 直接修改使用 canonical `file.edit/file.write`，兼容不同 agent 的工具名大小写；通过 shell 修改而缺少可靠证据的情形不伪造识别结果。
- `problem.vars.software` 只描述问题对象，不再自动成为 KB remedy 的安装依赖。依赖判定分别比较工具和软件命名空间，缺少观测时保留 unknown。
- 引擎版本为 `rec-engine-v2.1`，输入事实修订纳入缓存摘要；升级后不会继续命中原错误事实快照与旧推荐 run。

回归使用合成日志、伪造 agent home 和 FakeFetcher：验证实际推荐 gate、KB Hook 内容、第三方 Skill 引用、AI artifact、待获取状态、鉴权及 resolve/plan 内容一致性。测试不依赖真实用户日志、网络下载或付费模型。
