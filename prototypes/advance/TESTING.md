# 统一界面的测试

Playwright 验证 Lite / Advance 的浏览器行为、布局、状态与 live 接线。默认使用 Playwright 管理的 Chromium；明确需要本机 Chrome 时设置 `PLAYWRIGHT_CHANNEL=chrome`。

## 运行

从仓库根执行：

```sh
pnpm --filter @orbit/prototype-advance exec playwright install chromium
python3 scripts/heavy.py pnpm check:ui
```

可追加 `--project=mac-14` 缩小调试范围。单文件调试通过该包的 Playwright 命令选择 `tests/<文件>.spec.mjs`；项目尺寸与 worker 配置以 `playwright.config.mjs` 为准，不在文档复制固定用例总数。

## 覆盖与职责

`tests/` 按页面、通用交互、动效、布局、live API 和原生桥适配组织。场景与预期写在测试中；构造路由响应位于相应 fixture，不依赖真实个人历史。

修改源文件后重新 build；包的 check 验证产物同步。共享客户端先运行同步脚本，客户端 Node 测试与浏览器接线测试分别回答请求状态机和页面行为。

`tools/shoot.mjs` 用于截图查看，不替代断言。测试结果和截图输出保持忽略；无需为纯文档修改重新拍全部截图。原生菜单、通知、权限和打包另见[Mac App 验证](../../docs/development/mac-app.md)。

真实 gateway 旅程通过 `bash scripts/check.sh journey` 运行；普通 UI 测试未设 LIVE_GATEWAY 时会跳过并提示相关用例。会话摘要、阶段计数、播放头与独立滚动均有页面回归，测试总数由实际收集结果决定。
