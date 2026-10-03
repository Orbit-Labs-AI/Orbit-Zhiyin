"""Model identity and reasoning-effort normalization (pure functions, no I/O).

canonical id = `<creator>/<model>`: hosting/router prefixes, regions and deployment version
suffixes are removed; date snapshots stay part of the identity (`-20241022` and `-latest`
are aliases of a family, never merged). Reasoning effort is a run setting, not identity.
"""

import re

ROUTERS = {
    "bedrock", "bedrock_converse", "vertex_ai", "vertex_ai_beta", "azure", "azure_ai", "openrouter", "together_ai",
    "fireworks_ai", "groq", "deepinfra", "anyscale", "perplexity", "replicate", "sagemaker", "ollama", "ollama_chat",
    "cloudflare", "databricks", "watsonx", "nvidia_nim", "github", "github_copilot", "amazon-bedrock",
    "google-vertex", "google-vertex-anthropic", "azure-openai", "together", "fireworks", "vercel",
    "openai-compatible", "litellm_proxy", "snowflake", "oci", "nscale", "lambda_ai", "novita", "hyperbolic",
}
CREATORS = {"anthropic", "openai", "google", "gemini", "deepseek", "alibaba", "qwen", "meta", "meta-llama", "mistral",
            "mistralai", "xai", "cohere", "moonshotai", "zhipuai", "amazon", "ai21", "minimax"}
CREATOR_ALIAS = {"gemini": "google", "qwen": "alibaba", "meta-llama": "meta", "mistralai": "mistral"}
VENDOR_DOT = re.compile(r"^(?:anthropic|meta|amazon|cohere|mistral|ai21|deepseek|qwen|openai|google|writer)\.")
REGION = re.compile(r"^(?:us|eu|apac|global|us-gov|jp|au|ca)\.")
FAMILIES = [
    (re.compile(r"^claude"), "anthropic"), (re.compile(r"^(?:chat)?gpt|^o\d|^codex|^text-embedding|^davinci"), "openai"),
    (re.compile(r"^gemini|^gemma"), "google"), (re.compile(r"^deepseek"), "deepseek"), (re.compile(r"^qwen|^qwq"), "alibaba"),
    (re.compile(r"^llama|^meta-llama"), "meta"), (re.compile(r"^(?:mistral|mixtral|codestral|devstral|magistral)"), "mistral"),
    (re.compile(r"^grok"), "xai"), (re.compile(r"^command"), "cohere"), (re.compile(r"^(?:kimi|moonshot)"), "moonshotai"),
    (re.compile(r"^glm"), "zhipuai"),
]
LEVELS = ("minimal", "low", "medium", "high", "xhigh")
EFFORT_WORDS = r"(?:minimal|low|medium|high|x-?high|extra[- ]high|max)"
PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
TAIL = re.compile(r"[\s_-]+(" + EFFORT_WORDS + r")(?:[\s_-]+(?:reasoning|effort|thinking))?\s*$", re.I)
THINKING_TAIL = re.compile(r"[\s_-]+(?:\d+(?:\.\d+)?\s*k[\s_-]+)?thinking\s*$", re.I)


def _creator(base: str) -> str | None:
    return next((creator for pattern, creator in FAMILIES if pattern.search(base)), None)


def canonical_model_id(raw: str, provider: str | None = None) -> str:
    text = str(raw).strip().lower()
    provider = (provider or "").strip().lower() or None
    parts = text.split("/")
    while len(parts) > 1 and parts[0] in ROUTERS | CREATORS:
        head = parts.pop(0)
        if head in CREATORS:
            provider = head
    base = "/".join(parts)
    base = REGION.sub("", base)
    vendor = VENDOR_DOT.match(base)
    if vendor:
        provider = provider if provider in CREATORS else vendor.group(0)[:-1]
        base = base[vendor.end():]
    base = re.sub(r"-v\d+:\d+$", "", base)                   # Bedrock deployment revision
    base = re.sub(r"@(\d{8})$", r"-\1", base)                # Vertex date snapshot keeps identity
    base = re.sub(r"@[^/@]*$", "", base)                     # Vertex other revisions
    base = re.sub(r":[^/:]*$", "", base)                     # :latest / :0 / :free tags
    if provider not in CREATORS:  # Hosts/routers and unknown labels defer to the model family.
        provider = _creator(base) or (None if provider in ROUTERS else provider) or "unknown"
    provider = CREATOR_ALIAS.get(provider, provider)
    return f"{provider}/{base}"


def normalize_effort(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    budget = re.search(r"\b(\d+(?:\.\d+)?)\s*(k)?\b", text)
    tokens = float(budget.group(1)) * (1000 if budget.group(2) else 1) if budget else 0
    if tokens >= 1000 and (budget.group(2) or re.search(r"thinking|budget|tokens", text)):
        return "low" if tokens <= 4096 else "medium" if tokens <= 16384 else "high" if tokens <= 32768 else "xhigh"
    if re.search(r"\b(?:x-?high|extra[- ]high|max)\b", text):
        return "xhigh"
    word = re.search(r"\b(minimal|low|medium|high)\b", text)
    return word.group(1) if word else None


def split_effort(display: str) -> tuple[str, str | None]:
    """'GPT-5 (medium reasoning)' -> ('GPT-5', 'medium'); identity-bearing parentheses stay."""
    base, effort = str(display).strip(), None
    while True:
        paren = PAREN.search(base)
        if paren and re.search(r"thinking|reasoning|effort|budget|^\s*" + EFFORT_WORDS + r"\s*$", paren.group(1), re.I):
            effort = effort or normalize_effort(paren.group(1))
            base = base[:paren.start()]
            continue
        tail = TAIL.search(base)
        if tail:
            effort = effort or normalize_effort(tail.group(1))
            base = base[:tail.start()]
            continue
        thinking = THINKING_TAIL.search(base)
        if thinking:
            effort = effort or normalize_effort(thinking.group(0))
            base = base[:thinking.start()]
            continue
        return base.strip(), effort


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_benchmark_model(display: str, known_canonical: set[str]) -> str | None:
    """Unique match of a leaderboard display name against known canonical ids; ambiguity -> None."""
    base, _ = split_effort(display)
    if not base:
        return None
    wanted = {_key(base), _key(canonical_model_id(base).split("/", 1)[1])}
    hits = {cid for cid in known_canonical if _key(cid.split("/", 1)[-1]) in wanted}
    return hits.pop() if len(hits) == 1 else None
