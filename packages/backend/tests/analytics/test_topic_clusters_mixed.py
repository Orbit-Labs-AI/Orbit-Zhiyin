"""a4a6-B12: topic clustering on mixed Chinese/English text with shared boilerplate (real: 440 sessions; 160 here keeps the legacy novelty fit fast)."""

import random
import re

from orbit_backend.analytics.text import representation

BOILERPLATE = ("You are working in the orbit repository. Follow AGENTS.md, keep commits small "
               "and run the checks before you finish.\n请用中文回复，并在结束前总结改动。")
TOPICS = {
    "frontend": ["调整 CSS 布局", "button styles", "页面 响应式", "dark mode theme", "组件 样式",
                 "flexbox layout", "前端 组件"],
    "database": ["数据库 迁移", "sqlite migration", "索引 查询", "schema 字段", "SQL query plan",
                 "事务 回滚 数据", "foreign key"],
    "ml": ["训练 模型", "learning rate", "数据集 标注", "loss curve", "模型 评估", "pytorch checkpoint",
           "推理 精度"],
    "docs": ["文档 写作", "readme section", "教程 章节", "changelog entry", "文档 结构",
             "docstring examples", "说明 文档"],
}


def corpus(n=160, seed=7):
    rng = random.Random(seed)
    names = sorted(TOPICS)
    entities = []
    for i in range(n):
        topic = names[i % len(names)]
        body = "，".join(rng.sample(TOPICS[topic], 3))
        entities.append({"entity_id": f"s{i:03d}", "ts": i, "topic": topic,
                         "text": f"{BOILERPLATE}\n{body}"})
    return entities


def test_mixed_text_with_boilerplate_yields_word_level_balanced_topics():
    entities = corpus()
    truth = {e["entity_id"]: e["topic"] for e in entities}
    result = representation([{k: e[k] for k in ("entity_id", "ts", "text")} for e in entities])
    clustering = result["clustering"]
    assert clustering["status"] == "available", clustering
    assert clustering["boilerplate_line_n"] == 2
    assert 3 <= clustering["cluster_count"] <= 8
    assert clustering["largest_share"] <= 0.6
    for cluster in result["clusters"]:
        top = [t["term"] for t in cluster["top_terms"][:5]]
        # word-level labels, never 2-char Latin fragments such as "er" or "re"
        assert all(not re.fullmatch(r"[a-z]{1,2}", t) for t in top), top
        dominant = max(
            {truth[e] for e in cluster["entity_ids"]},
            key=lambda topic: sum(truth[e] == topic for e in cluster["entity_ids"]),
        )
        purity = sum(truth[e] == dominant for e in cluster["entity_ids"]) / cluster["size"]
        assert purity >= 0.9, (top, purity)


def test_unrelated_texts_fall_back_to_insufficient_not_one_giant_cluster():
    rng = random.Random(3)
    vocab = [f"w{i}x" for i in range(4000)]
    entities = [{"entity_id": f"e{i}", "ts": i, "text": BOILERPLATE + "\n" + " ".join(rng.sample(vocab, 6))}
                for i in range(60)]
    clustering = representation(entities)["clustering"]
    assert clustering["status"] == "insufficient"
    assert clustering["cluster_count"] is None


def test_clustering_is_deterministic():
    entities = corpus(80)
    strip = [{k: e[k] for k in ("entity_id", "ts", "text")} for e in entities]
    assert representation([dict(e) for e in strip]) == representation([dict(e) for e in strip])
