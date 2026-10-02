# Hackathon

ActionMesh AI 团队的 Hackathon 比赛项目。

## 先试后端

Tandem 后端读取本地 Codex 记录，按项目和模型整理，分析用户的协作要求与实际卡点，再找有对应处理办法的资源。中文解释是否容易理解，是当前 demo 的评价目标。当前 MVP 范围由三位成员确认；前端 [demo](docs/design/demo/tandem-demo.html) 仅作设计参考。

需要 Python 3.11 或更新版本。在仓库根目录运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/tandem demo
.venv/bin/tandem evaluate
.venv/bin/pytest -q
```

demo 使用虚构数据，CLI 按“数据 → 画像 → 瓶颈 → 推荐”直接展示。结果目录同时保存 `profile.md / bottlenecks.md / process.md / report.md` 及对应 JSON。评价结果在 `.local/evaluation.json`。通过自动检查表示已排除部分明显错误，仍需要读者验收。

```sh
.venv/bin/tandem demo --view profile
.venv/bin/tandem demo --view bottlenecks
.venv/bin/tandem demo --view process
```

不指定想要哪个 skill，也能先生成画像与瓶颈；资源目录只参与最后的匹配。推导过程见 [画像怎样产生](docs/backend/profiling.md)。这次展示使用 CLI，无需接入前端。

`evaluate` 跑文字对照、整条链路的构造场景，以及新增措辞和组合要求；`--suite pipeline / probe` 可以分别选择。结果保留误报、漏报和证据检查。这些样例用于改进规则；在独立临时数据库中运行，正常数据不会被改写。

## 用自己的 Codex 数据

```sh
.venv/bin/tandem import --codex-home "$HOME/.codex"
.venv/bin/tandem report
.venv/bin/tandem serve
```

报告在 `.local/report/`，API 文档在 <http://127.0.0.1:8765/docs>。真实聊天与派生结果只保存在忽略提交的 `.local/`。导入器只读 Codex 文件；默认服务监听本机。

分析和评价使用同一批数据时，用 `--before 2026-10-01T15:43:13Z` 固定导入快照，并通过 `--exclude-session` 排除测试与评价会话。不要把评价中用户给出的标准重新当作历史偏好导入。

已有快照和排除名单会保存在数据库中；重跑时省略参数仍沿用。`--reset-sample-policy` 才会重新设置范围，使用时需要重新指定仍应排除的评价会话。

## 核对推荐来源

离线目录自带 10 个公开来源的固定版本。需要重新核对时运行：

```sh
.venv/bin/tandem catalog-refresh
```

它从 GitHub 官方 API 读取仓库信息和 Markdown，核对版本与内容哈希，结果保存在 `.local/catalog.json`。`--latest` 才会更新到当前默认分支，`--resource-id humanizer-zh` 可以只核对一个来源。导入和分析不需要联网。

目录包括规则、skills、插件、MCP、hooks、基准和代理。现阶段只对分析中有明确匹配的 skill 建议一次小范围试用：必须同时有画像证据、瓶颈证据，以及适合场景和语言的资源。真实收益需要另测。

## 看实现与版本报告

- [先验这条链路](docs/backend/acceptance.md)
- [今晚先跑通什么](docs/backend/plan.md)
- [当前版本：完整保留材料缺口与离线证据](docs/backend/versions/v0.13.1.md)
- [怎样验“说人话”](docs/backend/reader-review.md)
- [各版记录](docs/backend/versions/README.md)
- [模块与接口](docs/backend/architecture.md)
- [这些数字说明什么](docs/backend/modeling.md)
- [调研与取舍](docs/backend/research.md)

官方 dsh 源码作为固定版本的 submodule 放在 `third_party/deepseek-harness`。需要查源码时运行 `git submodule update --init --depth 1`；它不参与后端启动。
