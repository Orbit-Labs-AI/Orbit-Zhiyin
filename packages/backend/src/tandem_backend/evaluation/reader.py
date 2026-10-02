"""Prepare reproducible reader comparisons without modifying historical evidence.

Mechanical checks verify literal facts and obvious problems. A reader separately
judges priorities, background fit and Chinese phrasing. Blank ratings stay unknown.
"""

import json
import random
import re
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from .readability import READABILITY_RULE_VERSION, SCENE_BUDGETS, evaluate_text

PACK_VERSION = "reader-pack-v1"
DIMENSIONS = {
    "priority": "能抓住主次和逻辑",
    "reader_fit": "符合指定读者的背景",
    "natural_chinese": "中文自然，语气尊重读者",
    "fact_fidelity": "保留事实、条件和不确定性",
}
MAX_JSON_BYTES = 2 * 1024 * 1024


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("评审文件过大")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("评审文件必须是 JSON 对象")
    return value


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z0-9_-]{1,64}", value))


def _string(value: object, limit: int = 2000) -> bool:
    return isinstance(value, str) and len(value) <= limit


def validate_corpus(corpus: dict) -> None:
    if corpus.get("schema_version") != "1.0" or corpus.get("purpose") != "evaluation_only":
        raise ValueError("案例必须声明支持的格式与 evaluation_only")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("需要 1 至 50 个评审案例")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not _identifier(case.get("id")) or case["id"] in seen:
            raise ValueError("案例 ID 无效或重复")
        seen.add(case["id"])
        if case.get("scene") not in SCENE_BUDGETS:
            raise ValueError("评审场景无效")
        if not all(_string(case.get(k), 1000) and case[k].strip() for k in ("reader", "task")):
            raise ValueError("需要指定读者和任务")
        facts = case.get("required_facts")
        if not isinstance(facts, list) or not 1 <= len(facts) <= 20 or not all(
                _string(f, 500) and f.strip() for f in facts):
            raise ValueError("需要列出共同核对的事实")
        variants = case.get("variants")
        if not isinstance(variants, list) or len(variants) != 2:
            raise ValueError("每个案例需要两种表达")
        if not all(isinstance(v, dict) and _identifier(v.get("id")) and
                   _string(v.get("text"), 30000) and v["text"].strip() for v in variants):
            raise ValueError("表达 ID 或正文无效")
        if variants[0]["id"] == variants[1]["id"]:
            raise ValueError("同一案例的表达 ID 不能重复")
        if any(v["id"] in ("tie", "neither") for v in variants):
            raise ValueError("表达 ID 不能使用评分保留字")


def _form(cases: list[dict], mapping: dict, form: str) -> str:
    lines = [f"# 读者评审 · {form}", "", "先读表达，再回答；最后展开事实核对。A、B 不表示新旧或好坏。",
             "", "评分分别看：" + "、".join(DIMENSIONS.values()) + "。",
             "", "每项按 0–4 评分：0 无法使用，1 大幅修改，2 有明显障碍，3 基本清楚，4 清楚且合适。无法判断请留空。",
             "", "评分表只记录评价，不会写入历史画像。", ""]
    for case in cases:
        variants = {v["id"]: v["text"] for v in case["variants"]}
        lines.extend([f"## {case['id']}", "", f"读者：{case['reader']}", "", f"任务：{case['task']}", ""])
        for slot in ("A", "B"):
            lines.extend([f"### 表达 {slot}", "", variants[mapping[case["id"]][slot]], ""])
        lines.extend(["先用自己的话写出重点，以及判断依据或下一步。再判断你愿意使用 A、B、两者都可或两者都需修改。",
                      "", "<details>", "<summary>读完后核对事实</summary>", ""])
        lines.extend("- " + fact for fact in case["required_facts"])
        lines.extend(["", "这些文字匹配只能帮助查遗漏；事实含义是否保留，仍需阅读判断。", "", "</details>", ""])
    return "\n".join(lines)


def _blank_ratings(manifest: dict, form: str) -> dict:
    return {"schema_version": "1.0", "purpose": "evaluation_only", "review_id": manifest["review_id"],
            "manifest_sha256": _digest(_canonical(manifest)), "form": form, "reviewer": "",
            "acceptance": {"decision": None, "scope": "listed_cases", "note": ""},
            "cases": [{"id": c["id"], "preferred": None, "main_point": "", "reason_or_next_step": "", "note": "",
                       "variants": {slot: {"scores": dict.fromkeys(DIMENSIONS), "usable": None, "note": ""}
                                    for slot in ("A", "B")}} for c in manifest["cases"]]}


def make_pack(output: Path, cases_file: Path | None = None, seed: int = 0) -> dict:
    """Freeze facts and counterbalance order; never replace a reader's annotations."""
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed 需要是 0 至 2^32-1 的整数")
    corpus = _read_json(cases_file) if cases_file else json.loads(
        files("tandem_backend").joinpath("data/reader_cases.json").read_bytes())
    validate_corpus(corpus)
    cases = corpus["cases"]
    corpus_hash = _digest(_canonical(corpus))
    review_id = "review-" + _digest(_canonical({"corpus": corpus_hash, "seed": seed, "version": PACK_VERSION,
                                             "checks": READABILITY_RULE_VERSION}))[:24]
    folder = output / review_id
    order = list(range(len(cases)))
    random.Random(seed).shuffle(order)
    swap = {index: position % 2 for position, index in enumerate(order)}
    mappings = {form: {} for form in ("X", "Y")}
    for index, case in enumerate(cases):
        ids = [v["id"] for v in case["variants"]]
        for form in mappings:
            first = swap[index] ^ (form == "Y")
            mappings[form][case["id"]] = {"A": ids[first], "B": ids[1 - first]}
    artifacts = {f"review-{form}.md": _form(cases, mappings[form], form).encode() for form in mappings}
    checks = {"purpose": "evaluation_only", "human_acceptance": "pending", "history_updated": False,
              "meaning": "字面事实和规则检查，不是读者评分。",
              "cases": [{"id": c["id"], "variants": {v["id"]: evaluate_text(v["text"], c["scene"], c["required_facts"])
                                                        for v in c["variants"]}} for c in cases]}
    artifacts["checks.json"] = json.dumps(checks, ensure_ascii=False, indent=2).encode()
    manifest = {"schema_version": "1.0", "purpose": "evaluation_only", "pack_version": PACK_VERSION,
                "review_id": review_id, "corpus_sha256": corpus_hash, "seed": seed, "forms": mappings,
                "cases": [{"id": c["id"], "scene": c["scene"], "reader": c["reader"],
                           "variant_sha256": {v["id"]: _digest(v["text"].encode()) for v in c["variants"]}} for c in cases],
                "artifacts_sha256": {name: _digest(value) for name, value in artifacts.items()}}
    artifacts["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    # Validate every frozen artifact before writing any files. A revised input
    # gets a different review ID, so earlier comparisons remain reproducible.
    for name, value in artifacts.items():
        target = folder / name
        if target.exists() and target.read_bytes() != value:
            raise ValueError("已有评审材料被修改，请保留原件并使用新的输出目录")
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        if not (folder / name).exists():
            (folder / name).write_bytes(value)
    for form in mappings:
        target = folder / f"ratings-{form}.json"
        if not target.exists():
            target.write_text(json.dumps(_blank_ratings(manifest, form), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"review_id": review_id, "folder": str(folder.resolve()), "cases": len(cases),
            "human_acceptance": "pending", "history_updated": False,
            "forms": {f: str((folder / f"review-{f}.md").resolve()) for f in mappings},
            "ratings": {f: str((folder / f"ratings-{f}.json").resolve()) for f in mappings}}


def reader_results(folder: Path, ratings_file: Path) -> dict:
    """Aggregate supplied labels, preserving missingness and explicit scope."""
    manifest = _read_json(folder / "manifest.json")
    ratings = _read_json(ratings_file)
    if manifest.get("schema_version") != "1.0" or manifest.get("purpose") != "evaluation_only":
        raise ValueError("评审材料格式无效")
    if (ratings.get("schema_version") != "1.0" or ratings.get("purpose") != "evaluation_only" or
            ratings.get("review_id") != manifest.get("review_id") or
            ratings.get("manifest_sha256") != _digest(_canonical(manifest))):
        raise ValueError("评分表与冻结材料不一致")
    for name, digest in manifest["artifacts_sha256"].items():
        if name not in ("review-X.md", "review-Y.md", "checks.json") or _digest((folder / name).read_bytes()) != digest:
            raise ValueError("评审正文或规则检查已改变，不能混用原评分")
    form = ratings.get("form")
    if form not in ("X", "Y") or not _string(ratings.get("reviewer"), 100):
        raise ValueError("评审表单或读者标记无效")
    rows = ratings.get("cases")
    expected_ids = {c["id"] for c in manifest["cases"]}
    if not isinstance(rows, list) or not all(isinstance(r, dict) and _identifier(r.get("id")) for r in rows) or len(rows) != len(expected_ids) or {
            r.get("id") for r in rows} != expected_ids:
        raise ValueError("评分案例缺失、重复或不属于本次评审")
    totals, preference_counts, completed = {}, {}, 0
    supplied = 0
    for row in rows:
        if row.get("preferred") not in (None, "A", "B", "tie", "neither") or not all(
                _string(row.get(k)) for k in ("main_point", "reason_or_next_step", "note")):
            raise ValueError("偏好或复述格式无效")
        preferred = row["preferred"]
        if preferred:
            key = manifest["forms"][form][row["id"]].get(preferred, preferred)
            preference_counts[key] = preference_counts.get(key, 0) + 1
            supplied += 1
        variants = row.get("variants")
        if not isinstance(variants, dict) or set(variants) != {"A", "B"}:
            raise ValueError("需要保留 A、B 两栏评分")
        supplied += sum(bool(row[k].strip()) for k in ("main_point", "reason_or_next_step", "note"))
        full = preferred is not None and bool(row["main_point"].strip()) and bool(row["reason_or_next_step"].strip())
        for slot, value in variants.items():
            if not isinstance(value, dict) or not _string(value.get("note")) or type(value.get("usable")) not in (bool, type(None)):
                raise ValueError("可用性或评语格式无效")
            scores = value.get("scores")
            if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS) or not all(
                    score is None or (type(score) is int and 0 <= score <= 4) for score in scores.values()):
                raise ValueError("分数需要是 0–4 的整数，无法判断时留 null")
            variant = manifest["forms"][form][row["id"]][slot]
            bucket = totals.setdefault(variant, {k: [] for k in DIMENSIONS})
            for dimension, score in scores.items():
                if score is not None:
                    bucket[dimension].append(score)
                    supplied += 1
            supplied += value["usable"] is not None
            supplied += bool(value["note"].strip())
            full &= value["usable"] is not None and all(s is not None for s in scores.values())
        completed += full
    acceptance = ratings.get("acceptance")
    if (not isinstance(acceptance, dict) or acceptance.get("decision") not in (None, "accept", "needs_revision") or
            acceptance.get("scope") != "listed_cases" or not _string(acceptance.get("note"))):
        raise ValueError("验收结论格式无效")
    if acceptance["decision"] is not None and (completed != len(rows) or not ratings["reviewer"].strip()):
        raise ValueError("明确验收前需要完成各案例评分并标记读者")
    status = "rated" if completed == len(rows) else ("partially_rated" if supplied else "pending")
    decision = acceptance["decision"]
    return {"review_id": manifest["review_id"], "form": form, "review_status": status,
            "cases": len(rows), "completed_cases": completed, "preference_counts": preference_counts,
            "scores": {variant: {d: {"mean": round(sum(v) / len(v), 3) if v else None, "rated": len(v)}
                                  for d, v in dimensions.items()} for variant, dimensions in totals.items()},
            "human_acceptance": {None: "pending", "accept": "reviewer_accepted", "needs_revision": "reviewer_needs_revision"}[decision],
            "acceptance_scope": "listed_cases", "reviewer": ratings["reviewer"], "acceptance_note": acceptance["note"],
            "history_updated": False, "limitation": "结果只描述本次读者与案例；没有评分不代表满意，也不证明资源收益。"}
