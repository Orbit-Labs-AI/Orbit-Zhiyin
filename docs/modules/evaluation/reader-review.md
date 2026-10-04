# 读者理解评价

先检查必要事实与条件是否保留，再评价读者能否理解重点和下一步。自动规则、独立人工评分和真实使用效果分别记录。

## 准备材料

```sh
uv run orbit reader-pack --output .local/reader-review
```

默认使用构造案例，比较同一事实的两种表达。自定义 `--cases` 需要声明 evaluation_only 和必要事实；评审命令不读取历史库，不把评价写入画像。

A/B 隐藏表达版本，另一份材料交换顺序。读者先看正文并写复述，再检查事实；同一读者的重复阅读不能当作独立样本。主次、背景适配、自然程度和事实保留分别评分，无法判断为 null。

## 汇总

```sh
uv run orbit reader-results --pack .local/reader-review --ratings .local/reader-review/ratings-X.json
```

未填写保持待评价，部分填写只汇总已有信息。正文或版本映射变化后不能混用旧评分。明确接受只适用于该读者与已评案例，不推广到全部任务。真实材料留在本地忽略目录，公开报告使用构造或充分脱敏摘要。
