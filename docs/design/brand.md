# Orbit 品牌

本页规定名称和素材使用。几何、颜色和字形数值以源参数及生成产物为唯一依据，文档不维护另一份可漂移参数表。

## 名称

产品名 **Orbit**，带字标时全名 **Orbit·知音**。界面版本写 **Lite / Advance**。包、CLI、环境变量和目录使用 `orbit`：`orbit_*`、`@orbit/*`、`ORBIT_*`、`orbit.db`、`Application Support/Orbit`。

GitHub 源码仓库统一为 [`Orbit-Labs-AI/Orbit-Source`](https://github.com/Orbit-Labs-AI/Orbit-Source)，本地项目根目录统一为 `Orbit/`（例如 `~/Projects/Orbit Labs/Orbit`）。安装包与更新说明继续发布在 [`Orbit-Labs-AI/Orbit`](https://github.com/Orbit-Labs-AI/Orbit/releases)。克隆地址、源码链接、界面示例与工作区引用随源码仓库名统一。

历史名称与数据迁移集中在 [orbit_data/legacy.py](../../packages/data/src/orbit_data/legacy.py)。旧分支接入时按[历史迁移说明](../archive/migrations/structure-migration.md)检查，不为新代码增加旧名别名。文档保留历史引用时应说明其时间范围。

## 标志与素材

锥形螺旋是 Orbit 标志。App 图标、透明标志、Dock 图标与菜单栏图均为同一几何的整体缩放，不重画或单独调整线宽。

| 场景 | 使用素材 |
| --- | --- |
| App / Dock | `logo/kit/app-icon/`、`logo/kit/dock/`，原生构建复制 `Orbit.icns` |
| 菜单栏 | `logo/kit/nav/` 的模板图，由系统着色 |
| 透明标志 | `logo/kit/mark/` |
| Orbit·知音 字标 | `logo/kit/wordmark/`，保留透明背景与纵横比 |
| favicon / 分享图 / 动效 | `logo/kit/favicon/`、`social/`、`motion/` |

完整文件与尺寸见[素材清单](logo/kit/manifest.json)。当前 README 继续使用透明底金色字标。浅色场景的常规字标用板岩灰，深色场景用香槟黄；不要通过滤镜改成近似颜色。

## 生成与验证

```sh
python3 docs/design/logo/generate.py
node docs/design/logo/export.mjs
```

`orbit-spec.json` 管参数，`generate.py` 生成矢量，`export.mjs` 渲染位图。正式 App 和原型引用生成文件；参数改动后同步相关嵌入资产并构建。`pnpm check:docs` 会核对矢量与素材尺寸。

字标的 O 由同一螺旋俯视投影，rbit、知音与间隔点使用已经提取的字形；[wordmark-glyphs.json](logo/wordmark-glyphs.json)保留来源和摘要。需要改变字体时先修改源配置并重新提取，不手绘字形。详细旧参数与来源记录见[品牌快照](../archive/design/brand-spec-2026-10-03.md)。

## App 字体

正文与控件使用 macOS 系统无衬线字体，中文回退 PingFang SC；类型码使用 `ui-rounded`，代码、路径与快捷键使用 `ui-monospace`。数字采用等宽数字特性，不因旧 `.mono` 类名就把普通元信息改成代码字体。

具体 token 在 `prototypes/advance/src/styles/00-base.css`。App 不打包或内联远程网页字体；品牌字标的轮廓素材与页面正文字体是不同用途。

历史变体在 `logo/variants/`，只作参考。当前人格之花属于[人格系统](persona/README.md)，不替代 App 标志。
