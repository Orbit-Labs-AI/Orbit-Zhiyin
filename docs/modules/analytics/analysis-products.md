# 组合分析与导出

`analytics/products` 在同一个分析快照中组织概览、工具、活动、任务、偏好、反馈、会话、项目、模型档位和文本统计。App 通过 uiview 和 live 绑定使用这些事实，CLI 可生成独立报告。

## API 与范围

| 入口 | 用途 |
| --- | --- |
| `GET /v1/analytics/products` | 完整组合结果 |
| `GET /v1/analytics/products/sessions` | 同范围会话检索与分页 |
| `GET /v1/analytics/products/compare` | 对比两个所选会话 |

沿用时间、项目、模型、档位、来源、根会话、排除项和子代理范围。`source_ids=` 明确选择零个来源；`with_text=true` 才增加文本表示。上期比较需有明确时间窗，不从任意缓存猜一个比较基期。

结果带 scope、版本、digest 和覆盖。比率等输出保留 value、unit、effective_n、unknown_n、status 与 basis；无数据和未知不填零。工具转移基于确定顺序，情绪表达不能视为用户心理真值。

## 命令行产物

```sh
uv run orbit --home .local/my-orbit analysis-report --display-timezone Asia/Shanghai --output .local/analysis-report
```

终端、JSON、CSV 与离线 HTML 从同一快照生成。来源文本需转义，CSV 避免公式执行；导出仍可能含私密内容，分享前检查。

构造流程可运行：

```sh
python3 scripts/heavy.py uv run python -m evals.analytics.products --synthetic --output .local/analysis-products-synthetic
```

它通过虚构原生来源导入、分析、API 对照和导出检查接线。真实数据模式须显式指定来源与输出；具体参数用 `--help` 核对。

## 完成与限制

接口接通、字段完整与算法准确率分别验证。`uiview.persona` 的 App 类型与 products 的描述性 profile 是不同结果；不能再用旧的 `type_code=null` 说明推断 App 没有类型。报告中的未知、部分覆盖和陈旧状态必须传到 UI。

结构见[特征分析](feature-analytics.md)，显示规则见[展示指标](presentation-metrics.md)，缓存和运行记录见[统计与历史](statistics-history.md)。
