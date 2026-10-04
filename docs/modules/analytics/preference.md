# 偏好与历史证据

Preference 区分用户明确声明的偏好、任务中的历史要求以及可选的推断观察。它们都保留来源和作用域，不因重复出现就变成全局规则。

## 作用域与时间

有效偏好按任务、项目、全局解释，显式请求覆盖与历史证据分别保留。撤销、替换、生效时间和冲突必须可追溯；多个同级值冲突时不能任挑其一，也不能退回低范围值掩盖冲突。

Instruction 记录当次执行要求，Preference 可复用其身份作为历史支持，但不自动提升为长期授权。一个会话含多个任务时，不能把其中一个任务偏好应用到全部任务。

## 证据输出

保留偏好维度、值、极性、作用域目标、证据事件、时间和规则版本。语言、篇幅、格式、工具、协作方式和任务/能力相关证据分别展示。引用、假设、代码与助手转述不当作用户自己的偏好。

语义观察只作为任务范围的低优先级推断，与显式声明和词面支持分开。无证据时保持未知，不以未识别证明“无偏好”。

## 接入与验证

实现位于 [analytics/preference](../../../packages/backend/src/orbit_backend/analytics/preference/)，通过 analytics 的偏好接口和 CLI 输出。消费者保持同一 Scope 与 evidence ID，不另建全局用户画像数据库。

### 本地验证脚本

```sh
bash scripts/check-preference.sh
uv run python -m evals.analytics.preference_local --db /absolute/orbit-home/orbit.db
```

第一条跑构造回归；第二条只读显式给定快照，参数见 `--help`。结果留在本地，真实文本不进 Git。历史五类验收及其样本边界见[审计记录](../../audits/preference-task-validation.md)，不作为当前独立质量认证。
