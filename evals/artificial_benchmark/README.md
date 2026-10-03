# Orbit artificial benchmark

SkillLearnBench-derived、history 到 held-out 的真实执行实验，不是官方榜单复现。
固定四个任务族（文件整理、GDP 表格、录用信、财务分析），每族实例 1–3
作为 history，4–6 作为 test。先采集 12 条 vanilla history；冻结个性化产物后，
三个实验组在相同的 12 道 test 上各执行一次。

## 隔离与冻结

Pi 使用新进程、新会话、新 agent 配置，关闭自动 skills、extensions、上下文文件、
prompt templates、主题、压缩和 cache warming。仅显式加载 `docker-tools.ts`，
把 Pi 标准 read/bash/edit/write 的执行后端替换为每次新建的 Docker 容器。
容器没有网络、宿主目录挂载或提供商凭据；Kimi 凭据只供宿主上的 Pi 调用 API，
运行后移除临时凭据文件。指定 `kimi-coding/k3` 和 `--thinking max`，同时核对
模型注册表确实将 max 映射为 max。
宿主内置工具用 `--no-builtin-tools` 禁用；扩展无法加载时不能退回宿主执行。
Pi 进程使用同一 study 的空 runtime 目录作为原生日志里的逻辑项目；
实际工具工作区始终是每次新建容器的 `/root`，会话、配置、任务文件均独立。

任务镜像删除上游随环境附带的 skills，不包含 tests 或 solution。
只有 agent 进程退出、容器内后台进程停止后才复制 verifier。
评分依赖预装，保留上游评分前后处理，包括 GDP 的 `ssconvert` 公式计算。
上游固定版本的 `weighted-gdp-calculation-2` 缺少 `test_outputs.py`，它的 history
轨迹保留，成绩为未知；不能记为失败、成功或借用另一实例的答案。

`prepare` 保存提示、数据和 verifier 哈希及 split 重叠审计；`build` 固定镜像 ID；
四族的容器工具与评分脚本通过 preflight 后才允许 `freeze`。
正式运行校验冻结哈希；失败和未知用量保留，不靠重跑挑选结果。
无 token 预算，每任务上限 200 个 agent turn、3600 秒；默认两路并发。

## 命令

从仓库根运行。输出必须放在本地忽略目录或专用外置盘；不要提交运行轨迹、数据库或凭据。

```sh
uv run python -m evals.artificial_benchmark.study prepare \
  --source /path/to/pinned/SkillLearnBench --study /path/to/new-study
uv run python -m evals.artificial_benchmark.study build --study /path/to/new-study
uv run python -m evals.artificial_benchmark.runner preflight --study /path/to/new-study
uv run python -m evals.artificial_benchmark.validation --study /path/to/new-study
uv run python -m evals.artificial_benchmark.study freeze --study /path/to/new-study
uv run python -m evals.artificial_benchmark.runner history --study /path/to/new-study
uv run python -m evals.artificial_benchmark.adaptation --study /path/to/new-study
uv run python -m evals.artificial_benchmark.evaluate run --study /path/to/new-study
uv run python -m evals.artificial_benchmark.evaluate report --study /path/to/new-study
```

Docker 可通过 `DOCKER_HOST` 选择独立实例，`--docker` 指定 CLI。
`ORBIT_BUILD_PROXY` 只作为构建期间的 HTTP/HTTPS proxy 参数；正式任务无网络。
`prepare --apt-mirror URL --pip-index HTTPS_URL` 可明确选择软件包镜像源；
URL 与生成的 Dockerfile 都进入冻结记录，不改变上游指定的 Python 包版本。
论文下载按完整版本 URL 缓存到 Docker 的构建缓存；下载成功并检查 PDF 文件头后才入缓存。
缓存不进入任务镜像，每道文件整理任务仍包含上游指定的 100 篇论文与原始文件名。
Colima 用户可把 `COLIMA_HOME`、`XDG_CACHE_HOME`、`DOCKER_CONFIG` 设到专用外置目录，
使用 `--mount none --activate=false --ssh-config=false` 创建独立 profile。
建议 4 CPU、8 GiB 内存、100 GiB 稀疏数据盘。外置盘断开前停止实验和虚拟机。

## 计量

逐 `message_end` 统计 provider 报告的 input、output、cacheRead、cacheWrite，
忽略重复汇总这些消息的 `agent_end`；reasoning 已含在 output，不重复加算。
缺失或失败请求的未知用量不记为零，单独保存已知小计。保存完整事件、会话、
工具调用、错误、最终回复、verifier 输出、产物、耗时及冻结版本。
history、adaptation 和 online execution 的消耗分开记录。

B 仅导入这 12 条新建 Pi history，由产品的 canonical connector、分析、features、
rec-engine-v2 和生成模板产生建议。依产品排序选中的规则、Prompt、Skill、Hook、workflow
转换到 Pi；Hook 执行原产品脚本，事件映射由适配器记录。模型保持固定，MCP/subagent
等 Pi 不支持的类型沿用产品 gate，并保存每项未物化的原因。目录使用产品自带种子，
不读取个人 catalog、标签或偏好。C 直接读取相同的完整 history bundle，生成一个 Skill。
生成 pack 显式提供空的现有规则与已装清单，避免产品默认扫描宿主的全局规则文件。
Prompt / workflow 使用产品已有片段；未填写的槽位和只有安装指引的条目记录为不可物化。
两组产物冻结后写入容器只读卷，原始事件会计量每轮实际注入的输入。

最终输出含逐题 CSV、分组/分任务族统计、配对胜平负、adaptation 摊销和七节报告。
单独报告 history/test 环境完全相同的实例；不把这些重叠任务解释为新数据泛化。
文件整理论文也逐 URL 检查部分重叠；输入下载和镜像文件哈希审计（若提供）一并冻结。

针对计量与 verifier 转换的回归检查：
`uv run pytest -q tests/regression/test_artificial_benchmark.py`。
