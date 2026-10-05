# 开发环境与运行入口

所有命令从仓库根执行。Orbit 使用一个 Python workspace 和一个 pnpm workspace，依赖版本由根锁文件管理。

## 依赖

| 工具 | 要求 | 用途 |
| --- | --- | --- |
| Python | 3.13，由 `.python-version` 固定 | backend、data、catalog |
| uv | 能读取仓库锁文件的版本 | Python 安装与运行 |
| Node.js | ≥24.7 | 内置 SQLite/zstd connector 与 UI 构建 |
| pnpm | 11.25.0，见 `packageManager` | TypeScript / UI workspace |
| Swift / Xcode Command Line Tools | Swift 5.9+；原生构建在 macOS | Swift 客户端与桌面宿主 |

```sh
git clone https://github.com/Orbit-Labs-AI/Orbit.git Orbit
cd Orbit
bash scripts/bootstrap.sh
```

bootstrap 执行锁定的 `uv sync --all-packages --dev` 与 `pnpm install`。普通启动不需要初始化 `third_party` 子模块；它们用于源码研究。

## 选择运行入口

| 入口 | 命令 | 用途 |
| --- | --- | --- |
| 离线 UI | 浏览器打开 `prototypes/advance/orbit-demo.html` | 构造数据界面演示 |
| CLI 示例 | `uv run orbit demo` | 验证数据、分析、报告链路 |
| 报告 API | `pnpm dev --home .local/demo/data` | `orbit serve`，默认 8765，提供 `/docs` |
| App gateway | 见下文 | live UI、后台 worker、SSE、安装和 AI |
| 原生 App | [Mac App 构建](mac-app.md) | 系统菜单、通知、窗口和 helper 生命周期 |

运行报告 API 前先生成示例。`pnpm dev` 将参数放在 `serve` 之前，因此 `--home` 可直接传入；要改端口使用 `uv run orbit --home .local/demo/data serve --port 8766`。

## 启动 App gateway

先构建统一界面，并生成一次示例数据。下面的 token 仅用于你的本地开发实例：

```sh
pnpm --filter @orbit/prototype-advance build
uv run orbit demo
export ORBIT_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
uv run orbit-helper gateway --home .local/demo/data --port 8766 --assets prototypes/advance/orbit-demo.html
```

gateway 监听 `127.0.0.1`。在本机浏览器打开 `http://127.0.0.1:8766/app#token=<本次令牌>`；适配层读取 fragment 后移除它。不要分享该地址或 token。原生宿主会自动生成并注入令牌，无需用户复制。

`/app` 与 `/lite` 提供页面，API 使用 Bearer 鉴权并验证 Host/Origin。这个服务与 `orbit serve` 不是同一个入口。测试或演示使用独立 home，避免启用真实来源；`ORBIT_HOME` 或 `--home` 不得与来源目录互相包含。

## 接下来

按[模块接入表](../architecture/module-map.md)定位实现，按[测试指南](testing.md)选择检查。UI 修改编辑 `src/`，再生成 HTML；品牌素材从现有资产引用，不手工改图标几何。
