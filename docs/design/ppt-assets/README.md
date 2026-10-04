# 路演组件素材

从可运行原型提取页面、组件和品牌资产，用于幻灯片和产品介绍。导出使用示例数据；实际源码版本写入 manifest，旧导出不自动跟随新界面变化。

## 输出

| 目录 | 内容 |
| --- | --- |
| `pages/` | Advance 9 页、Lite 4 页的完整窗口，各有浅色和深色 |
| `components/` | 各页顶层卡片、指标、图表面板、独立人格表盘、人格分享卡 |
| `desktop/` | 6 种桌面小组件、悬浮胶囊 5 种状态、展开态、菜单栏面板 |
| `controls/` | 侧栏、版本切换、工具栏、筛选、按钮、标签、开关等共用控件 |
| `flows/` | 设置六页、命令面板、分享预览、首次启动、来源选择、人格揭晓、安装预览与确认、问本地 Agent |
| `vectors/` | 从当前 DOM 导出的图表 SVG，解析颜色变量和可见样式 |
| `brand/` | [官方品牌文件](../brand.md)的原样副本 |
| `icons/` | 当前 UI 的图标路径，单独保存为 SVG |
| `sources/` | 可运行单文件 HTML，以及 26 份早期画板与 `canvas.json` 存档 |

默认写入忽略目录 `output/playwright/orbit-ppt-assets/`。离线 `index.html` 支持搜索和筛选，JSON/CSV manifest 记录来源、定位、尺寸和主题，设计 token 单独保存。

## 导出

完成 bootstrap、安装 Playwright Chromium并构建原型后：

```sh
python3 scripts/heavy.py node docs/design/ppt-assets/export.mjs
```

可选 `--routes persona --themes dark` 只导出一页/主题，`--shared-only` 选择共用控件，`--scale 2` 改像素密度，`--out <目录>` 改输出位置。所有参数以脚本为准，不新增平行依赖锁。

## 引用与检查

保持纵横比、透明背景和原品牌几何。SVG 依赖字体时用 PNG 固定外观；跨平台字体变化不等于同一套像素。引用人格、收益、人数或用量时注明示例，不作效果证明。

检查导出索引中的边界、文字、图表、长列表与主题。大型图片包、ZIP 和运行截图留在本地。现行人格素材见[人格之花](../persona/README.md)，完整设计入口见[设计导航](../README.md)。
