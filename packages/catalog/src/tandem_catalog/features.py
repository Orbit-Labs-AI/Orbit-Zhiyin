"""Auditable extraction and bilingual lexical chunks, never effectiveness labels."""

import re

from .contracts import Feature, Resource, digest

FEATURE_VERSION = "features-1"
CHUNK_VERSION = "heading-1200-120-v1"

# This shared vocabulary is deliberately small. Source text cannot add curated friction.
VOCABULARY = {
    ("domain", "git.pr"): ("pull request", "code review", "代码审查", "审查", "gh pr"),
    ("domain", "testing"): ("pytest", "test-driven", "testing", "测试", "验证"),
    ("domain", "debugging"): ("debug", "root cause", "调试", "根因", "重复失败"),
    ("domain", "writing"): ("writing", "co-author", "写作", "文档", "humanizer"),
    ("domain", "frontend"): ("react", "frontend", "next.js", "前端"),
    ("domain", "research"): ("research", "citation", "arxiv", "论文", "引用"),
    ("software", "github"): ("github", "gh pr"),
    ("software", "cloudflare"): ("cloudflare", "wrangler"),
    ("software", "docker"): ("docker", "容器"),
    ("software", "figma"): ("figma",),
    ("software", "vercel"): ("vercel",),
    ("tool_kind", "browser"): ("playwright", "browser", "浏览器"),
}


def lexical_tokens(text: str) -> list[str]:
    """Latin words + Han bigrams; avoids unicode61 treating a Chinese sentence as one word."""
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            tokens.append(run)
    return tokens


def extract(resource: Resource) -> list[Feature]:
    features = {(f.feature, f.value, f.origin): f for f in resource.features}
    text = "\n".join((resource.name, resource.summary, resource.body)).lower()
    for (key, value), words in VOCABULARY.items():
        found = next((word for word in words if word in text), None)
        if found:
            feature = Feature(feature=key, value=value, evidence=f"text contains: {found}")
            features.setdefault((key, value, feature.origin), feature)
    for agent in resource.agents:
        f = Feature(feature="agent", value=agent, origin="declared", evidence="source compatibility")
        features[(f.feature, f.value, f.origin)] = f
    for command in ("git", "gh", "pytest", "uv", "python", "pnpm", "npm", "wrangler", "docker", "latexmk"):
        if re.search(r"\b" + command + r"\b", text):
            f = Feature(feature="command", value=command, evidence=f"text token: {command}")
            features[(f.feature, f.value, f.origin)] = f
    for extension in sorted(set(re.findall(r"\.(py|ts|tsx|js|jsx|swift|rs|tex|md|pdf|docx|xlsx)\b", text))):
        f = Feature(feature="file_type", value="." + extension, evidence="file extension in text")
        features[(f.feature, f.value, f.origin)] = f
    return sorted(features.values(), key=lambda f: (f.feature, f.value, f.origin))


def chunks(resource: Resource) -> list[dict]:
    metadata = "\n".join(filter(None, [resource.name, resource.summary,
                         " ".join(f"{f.feature}: {f.value}" for f in resource.features)]))
    sections = [("metadata", "Overview", metadata)]
    if resource.body_policy == "licensed" and resource.body:
        heading, buffer = "Body", []
        for line in resource.body.splitlines():
            if re.match(r"^#{1,6}\s", line):
                if buffer:
                    sections.append(("body", heading, "\n".join(buffer)))
                heading, buffer = line.lstrip("# "), []
            else:
                buffer.append(line)
        if buffer:
            sections.append(("body", heading, "\n".join(buffer)))
    result, seen = [], set()
    for field, heading, content in sections:
        for start in range(0, len(content), 1080):
            text = content[start:start + 1200].strip()
            if not text or (field, text) in seen:
                continue
            seen.add((field, text))
            result.append({"field": field, "heading": heading[:300], "text": text,
                           "text_hash": digest(text), "ordinal": len(result), "start": start})
    return result
