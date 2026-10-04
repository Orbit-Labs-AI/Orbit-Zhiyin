# Orbit Backend

`orbit_backend` 提供应用编排、CLI、报告 API、App gateway、分析、推荐、AI、安装与导出。会话事实由 `orbit_data` 读取，资源索引由 `orbit_catalog` 管理，后端不维护平行原生日志解析器。

## 从仓库根运行

```sh
bash scripts/bootstrap.sh
uv run orbit demo
pnpm dev --home .local/demo/data
```

`orbit serve` 是报告 API；桌面界面使用 `orbit-helper gateway`。令牌和 live UI 启动见[开发环境](../../docs/development/setup.md)。Python 固定 3.13，使用根 `uv.lock`。

## 实现入口

| 目录 | 职责 |
| --- | --- |
| `application`、`cli`、`api` | 用例、命令与报告接口 |
| `services`、`appdb` | gateway、worker、任务与应用状态 |
| `analytics`、`profiling`、`features` | 同范围测量、画像与特征 |
| `uiview`、`realtime` | 页面组合与可观察运行态 |
| `recommend`、`ai`、`install` | 建议、可选模型任务、安装与撤销 |
| `reporting`、`exporting`、`evaluation` | 报告、导出和独立评价 |

旧入口通过兼容层导出，新业务逻辑放职责模块。范围、缺失值和证据遵循[契约](../../docs/contracts/README.md)。

## 验证与构建

```sh
python3 scripts/heavy.py uv run pytest -q packages/backend/tests
uv build --package orbit-backend
```

跨包接口另按[测试指南](../../docs/development/testing.md)验证。模块测试在本包 `tests/`，跨包与服务流程在根 `tests/`。真实会话和数据库不作为测试资源提交。完整导航见[模块参考](../../docs/modules/README.md)。
