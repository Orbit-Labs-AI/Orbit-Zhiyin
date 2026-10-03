"""Auditable extraction and bilingual lexical chunks, never effectiveness labels."""

import re

from .contracts import Feature, Resource, digest

FEATURE_VERSION = "features-3"
CHUNK_VERSION = "heading-1200-120-v1"
EMBED_CHUNKS = 4
EXTRACTED_FRICTION_WEIGHT = 0.6  # Below curated (1.0): text mentioning a problem is not proof it solves it.

# Bilingual lexical vocabulary. Source text never adds *curated* features; friction values are
# the six session-side ids in orbit_backend.features.vocab.FRICTION (without the namespace).
VOCABULARY = {
    # friction (extracted, weight 0.6)
    ("friction", "retry_same_call"): ("retry", "retries", "retry loop", "重试", "失败后重复", "失败后", "原样重试",
                                      "circuit breaker", "熔断"),
    ("friction", "approval_wait"): ("permission prompt", "allowlist", "allow list", "auto-approve", "approve",
                                    "approval", "授权", "审批", "免确认"),
    ("friction", "readonly_prompted"): ("allowlist", "allow list", "read-only", "readonly", "只读"),
    ("friction", "destructive_cmd"): ("rm -rf", "force push", "force-push", "git reset --hard", "destructive",
                                      "破坏性", "误删"),
    ("friction", "long_tool_wait"): ("timeout", "long-running", "long running", "hangs", "超时", "长时间", "卡住"),
    ("friction", "tool_error"): ("error handling", "environment setup", "missing dependency", "exit code",
                                 "环境问题", "报错", "依赖缺失"),
    # domain
    ("domain", "git.pr"): ("pull request", "code review", "代码审查", "审查", "gh pr"),
    ("domain", "testing"): ("pytest", "test-driven", "testing", "unit test", "测试", "验证"),
    ("domain", "debugging"): ("debug", "debugging", "root cause", "调试", "根因", "重复失败"),
    ("domain", "writing"): ("writing", "co-author", "写作", "文档", "humanizer"),
    ("domain", "frontend"): ("react", "frontend", "next.js", "前端", "css", "tailwind"),
    ("domain", "research"): ("research", "citation", "arxiv", "论文", "引用"),
    ("domain", "git"): ("git", "commit", "rebase", "branch", "提交", "分支"),
    ("domain", "deploy"): ("deploy", "deployment", "release", "部署", "发布"),
    ("domain", "ci"): ("ci/cd", "continuous integration", "github actions", "pipeline", "持续集成"),
    ("domain", "security"): ("security", "vulnerability", "secret scanning", "安全", "漏洞"),
    ("domain", "database"): ("database", "sql", "migration", "数据库", "迁移"),
    ("domain", "data"): ("data analysis", "dataframe", "pandas", "csv", "数据分析"),
    ("domain", "ml"): ("machine learning", "pytorch", "training", "fine-tune", "模型训练", "机器学习"),
    ("domain", "docs"): ("documentation", "readme", "docstring", "说明文档"),
    ("domain", "refactor"): ("refactor", "重构"),
    ("domain", "performance"): ("performance", "profiling", "benchmark", "性能"),
    ("domain", "api"): ("rest api", "openapi", "graphql", "api design", "接口"),
    ("domain", "mobile"): ("ios", "android", "swiftui", "react native", "移动端"),
    ("domain", "design"): ("ui design", "design system", "mockup", "设计稿", "设计系统"),
    ("domain", "infra"): ("kubernetes", "terraform", "infrastructure", "基础设施"),
    ("domain", "observability"): ("logging", "monitoring", "tracing", "observability", "日志", "监控"),
    ("domain", "planning"): ("planning", "todo", "task list", "计划", "规划"),
    ("domain", "context"): ("context window", "compact", "token usage", "上下文", "压缩"),
    ("domain", "document"): ("pdf", "docx", "xlsx", "pptx", "spreadsheet", "表格", "幻灯片"),
    ("domain", "latex"): ("latex", "overleaf", "bibtex"),
    ("domain", "i18n"): ("i18n", "localization", "translation", "翻译", "本地化"),
    ("domain", "productivity"): ("calendar", "email", "inbox", "meeting", "meetings", "日程", "会议", "邮件"),
    ("domain", "finance"): ("finance", "financial", "invoice", "accounting", "payment", "payments", "stock", "金融", "财务"),
    ("domain", "ecommerce"): ("ecommerce", "e-commerce", "shopping", "storefront", "电商"),
    ("domain", "media"): ("video", "image", "images", "audio", "photo", "photos", "camera", "视频", "图片", "音频"),
    ("domain", "web_data"): ("web search", "scraping", "scraper", "crawler", "crawl", "爬虫"),
    ("domain", "agents"): ("multi-agent", "agent sdk", "subagent", "subagents", "orchestration", "多代理"),
    ("domain", "product"): ("product management", "product manager", "prd", "roadmap", "user research", "产品经理"),
    ("domain", "analytics"): ("analytics", "dashboard", "dashboards", "metrics", "数据看板"),
    ("domain", "communication"): ("chat", "messaging", "communications", "notification", "沟通"),
    ("domain", "hooks"): ("hook", "hooks", "pretooluse", "posttooluse"),
    ("domain", "maps"): ("maps", "geocoding", "google maps", "地图"),
    ("domain", "legal"): ("legal", "gdpr", "lawyer", "法律", "合同"),
    # software
    ("software", "github"): ("github", "gh pr"),
    ("software", "gitlab"): ("gitlab",),
    ("software", "git"): ("git",),
    ("software", "cloudflare"): ("cloudflare", "wrangler"),
    ("software", "docker"): ("docker", "容器", "dockerfile"),
    ("software", "kubernetes"): ("kubernetes", "kubectl", "k8s"),
    ("software", "terraform"): ("terraform",),
    ("software", "aws"): ("aws", "aws lambda"),
    ("software", "gcp"): ("gcp", "google cloud", "bigquery"),
    ("software", "azure"): ("azure",),
    ("software", "figma"): ("figma",),
    ("software", "vercel"): ("vercel",),
    ("software", "netlify"): ("netlify",),
    ("software", "supabase"): ("supabase",),
    ("software", "firebase"): ("firebase",),
    ("software", "postgres"): ("postgres", "postgresql", "psql"),
    ("software", "mysql"): ("mysql",),
    ("software", "sqlite"): ("sqlite",),
    ("software", "redis"): ("redis",),
    ("software", "mongodb"): ("mongodb", "mongo"),
    ("software", "sentry"): ("sentry",),
    ("software", "slack"): ("slack",),
    ("software", "notion"): ("notion",),
    ("software", "jira"): ("jira",),
    ("software", "stripe"): ("stripe",),
    ("software", "playwright"): ("playwright",),
    ("software", "puppeteer"): ("puppeteer",),
    ("software", "xcode"): ("xcode",),
    ("software", "arxiv"): ("arxiv",),
    ("software", "latex"): ("latex", "latexmk"),
    ("software", "obsidian"): ("obsidian",),
    ("software", "jupyter"): ("jupyter", "ipynb"),
    ("software", "pytest"): ("pytest",),
    ("software", "pnpm"): ("pnpm",),
    ("software", "npm"): ("npm",),
    ("software", "uv"): ("uv run", "uv sync"),
    ("software", "zoom"): ("zoom",),
    ("software", "dropbox"): ("dropbox",),
    ("software", "google_workspace"): ("gmail", "google calendar", "google drive", "google docs", "google sheets"),
    ("software", "canva"): ("canva",),
    ("software", "linear"): ("linear app", "linear issue", "linear issues"),
    ("software", "hubspot"): ("hubspot",),
    ("software", "salesforce"): ("salesforce",),
    ("software", "shopify"): ("shopify",),
    ("software", "discord"): ("discord",),
    ("software", "telegram"): ("telegram",),
    ("software", "airtable"): ("airtable",),
    ("software", "asana"): ("asana",),
    ("software", "confluence"): ("confluence",),
    ("software", "twilio"): ("twilio",),
    ("software", "openai"): ("openai", "chatgpt"),
    ("software", "adobe"): ("adobe", "photoshop", "premiere"),
    # programming languages and mainstream frameworks
    ("software", "python"): ("python", "pyproject", "pip install"),
    ("software", "typescript"): ("typescript", "tsconfig"),
    ("software", "javascript"): ("javascript", "node.js", "nodejs"),
    ("software", "rust"): ("rust", "cargo"),
    ("software", "go"): ("golang", "go.mod", "go module"),
    ("software", "java"): ("java", "maven", "gradle"),
    ("software", "kotlin"): ("kotlin",),
    ("software", "swift"): ("swift", "swiftui"),
    ("software", "csharp"): ("c#", "dotnet", "asp.net"),
    ("software", "cpp"): ("c++", "cmake"),
    ("software", "ruby"): ("ruby", "rails"),
    ("software", "php"): ("php", "laravel"),
    ("software", "react"): ("react", "next.js", "nextjs"),
    ("software", "vue"): ("vue", "nuxt"),
    ("software", "angular"): ("angular",),
    ("software", "svelte"): ("svelte", "sveltekit"),
    ("software", "django"): ("django",),
    ("software", "flask"): ("flask",),
    ("software", "fastapi"): ("fastapi",),
    ("software", "spring"): ("spring boot",),
    ("software", "flutter"): ("flutter", "dart"),
    ("tool_kind", "browser"): ("playwright", "browser", "浏览器"),
}
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Notification", "Stop", "SubagentStop",
               "SessionStart", "SessionEnd", "PreCompact")
_ASCII = re.compile(r"^[a-z0-9 ./+#-]+$")


# "uv" only as a command ("uv run"), never a bare word ("UV mapping"); see test_storage.
COMMANDS = re.compile(r"\b(git|gh|pytest|python|pnpm|npm|wrangler|docker|latexmk)\b|\b(uv)\s+(?:run|sync|add|pip|tool|venv)\b")
# No ".md": every skill, rule and agent file is Markdown, so it says nothing about the resource.
EXTENSIONS = re.compile(r"\.(py|ts|tsx|js|jsx|swift|rs|tex|pdf|docx|xlsx)\b")
# Extraction weighting. Evidence mass = HEAD_MASS per hit in name/summary + 1 per hit in the
# first BODY_HEAD_CHARS of the body + LATE_MASS per later hit; GENERIC words count half. The
# feature weight saturates like BM25 with k1=1: weight = mass / (mass + 1), so one name/summary
# hit gives 0.75, one early body hit 0.5, a single late mention 0.23. A feature is emitted only
# from weight >= MIN_WEIGHT (one early body hit, two late generic ones are not enough).
HEAD_MASS, LATE_MASS, BODY_HEAD_CHARS, MIN_WEIGHT = 3.0, 0.3, 2000, 0.5
# Words present in >= 5 % of the 1311 listable seed items (measured 2026-10-03 with
# vocabulary_hits over name+summary+body); they mostly appear in passing.
GENERIC = frozenset({"github", "security", "testing", "performance", "documentation", "deployment", "database",
                     "debugging", "writing", "browser", "monitoring", "pipeline", "git", "sql", "infrastructure",
                     "error handling", "logging", "planning", "observability", "migration", "debug", "ci/cd"})
_ASCII_WORDS = {w for words in VOCABULARY.values() for w in words if _ASCII.match(w)}
_HAN_WORDS = sorted({w for words in VOCABULARY.values() for w in words} - _ASCII_WORDS)
_ALNUM = re.compile(r"[a-z0-9]+")
# Latin words need token boundaries ("pr" must not hit "prompt"): bucket every word by its first
# alphanumeric token, then confirm candidates only at token starts. Han words match as substrings.
_BY_FIRST_TOKEN: dict[str, list[str]] = {}
for _word in sorted(_ASCII_WORDS):
    _BY_FIRST_TOKEN.setdefault(_ALNUM.match(_word).group(), []).append(_word)


def vocabulary_hits(text: str) -> dict[str, list[int]]:
    """Vocabulary word -> character offsets of its occurrences in lower-cased ``text``."""
    hits: dict[str, list[int]] = {}
    for token in _ALNUM.finditer(text):
        start = token.start()  # Maximal [a-z0-9]+ runs: the left boundary holds by construction.
        for word in _BY_FIRST_TOKEN.get(token.group(), ()):
            end = start + len(word)
            if text.startswith(word, start) and not (end < len(text) and text[end].isascii() and text[end].isalnum()):
                hits.setdefault(word, []).append(start)
    for word in _HAN_WORDS:
        start = text.find(word)
        while start >= 0:
            hits.setdefault(word, []).append(start)
            start = text.find(word, start + len(word))
    return hits


def lexical_tokens(text: str) -> list[str]:
    """Latin words + Han bigrams; avoids unicode61 treating a Chinese sentence as one word."""
    # "_" splits like FTS5 unicode61 does; a "a_b" token would become an unsupported phrase query.
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            tokens.append(run)
    return tokens


def _structured(resource: Resource) -> list[Feature]:
    """hook_event / transport / env_required from declared manifest and install hints."""
    from .risk import declared_env
    out = []
    manifest, install = resource.manifest or {}, resource.install or {}
    events = set()
    for container in (manifest.get("hooks"), (install.get("hook") or {}) if isinstance(install.get("hook"), dict) else {},
                      manifest):
        if isinstance(container, dict):
            events.update(k for k in container if k in HOOK_EVENTS)
            if isinstance(container.get("event"), str) and container["event"] in HOOK_EVENTS:
                events.add(container["event"])
    if resource.type == "hook" and not events:
        text = "\n".join((resource.summary, resource.body))
        events.update(e for e in HOOK_EVENTS if re.search(r"\b" + e + r"\b", text))
    out.extend(Feature(feature="hook_event", value=e, origin="declared", evidence="hook event") for e in sorted(events))
    transports = set()
    if resource.type == "mcp_server":
        for package in manifest.get("packages") or []:
            if isinstance(package, dict):
                transport = package.get("transport")
                transports.add(str((transport or {}).get("type") if isinstance(transport, dict) else transport or "stdio"))
        for remote in manifest.get("remotes") or []:
            if isinstance(remote, dict) and remote.get("type"):
                transports.add(str(remote["type"]))
        mcp = install.get("mcp") if isinstance(install.get("mcp"), dict) else {}
        if mcp.get("command"):
            transports.add("stdio")
        elif mcp.get("url"):
            transports.add(str(mcp.get("type") or "http"))
    out.extend(Feature(feature="transport", value=t[:256], origin="declared", evidence="mcp manifest")
               for t in sorted(transports) if t and t != "None")
    out.extend(Feature(feature="env_required", value=e["name"][:256], origin="declared",
                       evidence="secret" if e["secret"] else "env") for e in declared_env(manifest)[:30])
    return out


def extract(resource: Resource) -> list[Feature]:
    features = {(f.feature, f.value, f.origin): f for f in resource.features}
    head = "\n".join((resource.name, resource.summary)).lower()
    body = resource.body.lower()
    text = head + "\n" + body
    head_hits, body_hits = vocabulary_hits(head), vocabulary_hits(body)
    for (key, value), words in VOCABULARY.items():
        # One occurrence per position: nested words ("失败后重复" / "失败后") are one mention.
        head_at, body_at, used = {}, {}, []
        for word in words:
            factor = 0.5 if word in GENERIC else 1.0
            for hits, seen in ((head_hits, head_at), (body_hits, body_at)):
                for at in hits.get(word, ()):
                    seen[at] = max(seen.get(at, 0.0), factor)
            if word in head_hits or word in body_hits:
                used.append(word)
        mass = sum(HEAD_MASS * f for f in head_at.values()) + sum(
            (1.0 if at < BODY_HEAD_CHARS else LATE_MASS) * f for at, f in body_at.items())
        counts = [f"{w}×{len(head_hits.get(w, ())) + len(body_hits.get(w, ()))}" for w in used]
        weight = mass / (mass + 1)
        if weight >= MIN_WEIGHT:
            if key == "friction":
                weight *= EXTRACTED_FRICTION_WEIGHT
            feature = Feature(feature=key, value=value, weight=round(weight, 3),
                              evidence="text contains: " + ", ".join(counts[:3]))
            features.setdefault((key, value, feature.origin), feature)
    for agent in resource.agents:
        f = Feature(feature="agent", value=agent, origin="declared", evidence="source compatibility")
        features[(f.feature, f.value, f.origin)] = f
    for f in _structured(resource):
        features.setdefault((f.feature, f.value, f.origin), f)
    for command in sorted({a or b for a, b in COMMANDS.findall(text)}):
        f = Feature(feature="command", value=command, evidence=f"text token: {command}")
        features[(f.feature, f.value, f.origin)] = f
    for extension in sorted(set(EXTENSIONS.findall(text))):
        f = Feature(feature="file_type", value="." + extension, evidence="file extension in text")
        features[(f.feature, f.value, f.origin)] = f
    return sorted(features.values(), key=lambda f: (f.feature, f.value, f.origin))[:200]


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
            # Overview + first three body chunks get vectors; FTS indexes every chunk.
            result.append({"field": field, "heading": heading[:300], "text": text,
                           "text_hash": digest(text)[:32], "ordinal": len(result), "start": start,
                           "embed": int(len(result) < EMBED_CHUNKS)})
    return result
