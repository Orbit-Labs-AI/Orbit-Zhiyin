# 质量与真实数据验收

Pi memory-off、Kimi K3 max 的真实任务对照实验见 [Artificial benchmark](artificial_benchmark/README.md)。任务、镜像、提示与评分代码先冻结，原始轨迹与结果保留在本地忽略目录或专用外置盘。

从仓库根通过模块方式运行：

```sh
uv run tandem evaluate
uv run python -m evals.analytics.subjective_outcomes
uv run python -m evals.analytics.instruction_real --help
uv run python -m evals.analytics.semantic_history --help
uv run python -m evals.analytics.preference_local --help
```

subjective_outcomes 默认只使用构造质量样本；真实历史必须同时明确提供 --real-db 和 --codex-home。其他真实数据工具也需显式输入路径。输出保留在忽略的 .local 下，不能提交真实会话。

Preference 一键验证：`bash scripts/check-preference.sh`。指定 `--db /path/to/canonical/tandem.db` 后追加只读快照诊断；只运行快照诊断可用 `uv run --locked python -m evals.analytics.preference_local --db /path/to/canonical/tandem.db`。支持时间、项目与排除会话筛选，详见 [用法与输出](../docs/modules/analytics/preference.md#本地验证脚本)。不导入来源、不迁移旧库，也不以这个局部验证代替完整 API 验收。

原来 subjective_outcomes 中的性能测试已拆到 [benchmarks](../benchmarks/README.md)。运行时 API 使用的评价函数与内置 JSON 样本仍随 backend wheel 分发，不能移到仓库工具后造成安装版本缺文件。

这里的构造预期用于发现规则错误；读者评价另见[方法与限制](../docs/modules/evaluation/reader-review.md)。自动通过不代表真实推荐效果或人类认可。

推荐的过去到未来评测见 [Benchmark](benchmark/README.md)：`bash scripts/check-benchmark.sh` 从已有本机 canonical 快照冻结滚动锚点的推荐，单独观察最多 72 小时内接下来的任务，重放窗口／缺失／跨项目／表示对照。它使用 `.venv`，不调用模型或执行 Skill；有真实配对执行记录后才能计算效用与 Regret，缺失时明确为未证实。

已有本机 canonical 快照时，运行 `bash scripts/check-feature-diagnostics.sh`，直接在终端查看八个特征族和每个 Skill 的输入使用、有效观察、未知原因与推荐依据。使用仓库 `.venv`，无需 `uv`，不导入来源、不调用模型。默认七天窗口以快照最新事件为截止点，默认本机快照为 `.local/backend-nine-hour/current-data`；其他目录用 `--home` 指定。完整结果留在新建的忽略目录，详见[特征与 Skill 诊断](../docs/modules/analytics/fact-diagnostics.md)。

分析／推荐鲁棒性：`.venv/bin/python -m evals.analytics.robustness --home /path/to/canonical --output .local/robustness/run-01`。受控重试、失败消融、顺序／重复、范围、上下文与重复运行都有固定预期和关系检查。原生全量／增量、损坏日志、规模测试分别由 `robustness_native / robustness_faults / robustness_scale` 提供，命令与事实边界见[鲁棒性验收](../docs/development/analytics-robustness.md)。

推荐构造验收：`uv run python -m evals.recommendation.demo`；显式资源目录验证：`uv run python -m evals.recommendation.catalog /path/to/catalog --agent codex`。后者只校验提供的 JSON，不读取历史、不抓取资源。

推荐偏好／收益验收：`bash scripts/test-recommend.sh`。运行推荐模块和报告集成测试，再用四个已抓取公共 Skill 的内容审阅元数据生成用户／项目／任务对照案例、收益敏感性与边界报告。输出在 `.local/recommendation-validation/`，失败返回非零退出码。`--skip-tests` 只重生成案例并明确标记自动测试未运行，`--output /path/to/output` 可指定目录。该工具不执行上游 Skill，不读取真实用户历史，不自动联网；可选的本地抓取快照仅用于核对固定来源。

报告快照见[推荐测试报告](../docs/modules/recommendation/validation.md)。自动运行的案例带预先固定的预期首选和净收益断言；所有改善比例／成本均为构造假设，不是实测效果。四项评测元数据不是对 1033 项抓取结果的批量审核，也不随 backend wheel 默认发布。

## 本机 Codex 日志到 Skill 推荐

```sh
bash scripts/test-local-codex-recommend.sh
```

这条命令明确启用真实来源，默认只读 `$CODEX_HOME`（未设置则 `~/.codex`）中最近更新的 20 个允许导入的会话文件，通过 Python canonical connector 在独立数据库中索引来源，核验证据，运行 analytics 和 Skill 推荐。它不会运行构造案例；默认资源是上述四个有固定来源的公共 Skill 内容审阅元数据。环境只默认确定 agent=codex，其余条件未知时保留 needs_context。

`--latest 0` 导入全部允许的会话文件，`--codex-home /path/to/codex` 指定来源；`--context /path/to/context.json` 提供已确认的工具、权限和偏好，`--catalog /path/to/skills.json` 替换资源 envelope，`--from-ts / --until-ts` 用 UTC 毫秒选择分析范围。不会联网、安装或执行 Skill，也不会修改源日志。

每次运行创建 `.local/codex-recommend/run-<时间>-<标识>/`，保存 `data/tandem.db`、selection / import / verify / analytics / recommendations / summary JSON 和 `report.md`。原生来源按当前数据层契约就地只读索引，不另存原始日志副本；后续回查证据仍依赖来源文件。真实结果只留在忽略目录。显式 `--output` 必须是新目录，避免旧会话混入新样本；仓库内输出必须位于 `.local`。

端到端工具同时保存八族／逐 Skill 诊断和 `invariants.json`：检查主会话真人分母、任务成员归属、推荐信号与证据回溯、时间可见性及未知环境。关系断裂时失败，不会标成链路完成。


采集后来源被追加不影响本次运行：重算只投影已采集的字节，追加部分留给下一次导入。若某文件在采集后被改写，导入会跳过该文件（`skipped_files`，核验为 partial、状态 changed），脚本对同一组选中文件重新导入，最多尝试三次；来源持续被改写、缺失或核验不完整时失败退出，不缩小样本或忽略核验错误。

退出码 0 表示完成并产生 Skill 推荐，2 表示链路完成但没有匹配，1 表示导入／核验／分析失败。零推荐不会回退到构造数据或自动降低门槛；具体原因保留在 recommendations.json 的 assessments、excluded_resources 和 diagnostics。未提供成本及改善假设时，收益仍为未知。

UI 分析组合验收：`uv run python -m evals.analytics.products --synthetic`；真实来源通过 `--source AGENT=ROOT` 显式启用，命令、样本范围和报告见[分析验收](../docs/modules/analytics/analysis-products.md)。
