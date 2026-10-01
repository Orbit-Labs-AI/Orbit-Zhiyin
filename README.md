# Hackathon

ActionMesh AI 团队的 Hackathon 比赛项目。

## 先试后端

Tandem 后端读取本地 Codex 记录，按项目和模型整理，输出有证据的协作要求、待复核的瓶颈和写作 skill 建议。当前 MVP 范围由三位成员确认；前端 [demo](docs/design/demo/tandem-demo.html) 仅作设计参考。

需要 Python 3.11 或更新版本。在仓库根目录运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/tandem demo
.venv/bin/tandem evaluate
.venv/bin/pytest -q
```

demo 使用虚构数据，结果在 `.local/demo/report.md`。评价结果在 `.local/evaluation.json`。通过自动检查表示已排除部分明显错误，仍需要读者验收。

## 用自己的 Codex 数据

```sh
.venv/bin/tandem import --codex-home "$HOME/.codex"
.venv/bin/tandem report
.venv/bin/tandem serve
```

报告在 `.local/report/`，API 文档在 <http://127.0.0.1:8765/docs>。真实聊天与派生结果只保存在忽略提交的 `.local/`。导入器只读 Codex 文件；默认服务监听本机。

分析和评价使用同一批数据时，用 `--before 2026-10-01T15:43:13Z` 固定导入快照，并通过 `--exclude-session` 排除测试与评价会话。不要把评价中用户给出的标准重新当作历史偏好导入。

## 看实现与版本报告

- [今晚先跑通什么](docs/backend/plan.md)
- [v0.1：数据流已跑通，语义分类仍需修正](docs/backend/versions/v0.1.md)
- [v0.2：推荐开始由分析结果决定](docs/backend/versions/v0.2.md)
- [v0.2.1：修正快照与需求理解](docs/backend/versions/v0.2.1.md)
- [模块与接口](docs/backend/architecture.md)
- [调研与取舍](docs/backend/research.md)

官方 dsh 源码作为固定版本的 submodule 放在 `third_party/deepseek-harness`。需要查源码时运行 `git submodule update --init --depth 1`；它不参与后端启动。
