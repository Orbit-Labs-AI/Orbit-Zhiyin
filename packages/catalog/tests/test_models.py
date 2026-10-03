import pytest

from tandem_catalog.models import (
    canonical_model_id,
    normalize_effort,
    resolve_benchmark_model,
    split_effort,
)


@pytest.mark.parametrize("raw,provider,expected", [
    ("claude-3-5-sonnet-20241022", "anthropic", "anthropic/claude-3-5-sonnet-20241022"),
    ("claude-3-5-sonnet-latest", None, "anthropic/claude-3-5-sonnet-latest"),
    ("bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0", "bedrock", "anthropic/claude-3-5-sonnet-20241022"),
    ("anthropic.claude-3-haiku-20240307-v1:0", "amazon-bedrock", "anthropic/claude-3-haiku-20240307"),
    ("eu.anthropic.claude-3-7-sonnet-20250219-v1:0", None, "anthropic/claude-3-7-sonnet-20250219"),
    ("vertex_ai/claude-3-5-sonnet@20240620", "vertex_ai", "anthropic/claude-3-5-sonnet-20240620"),
    ("vertex_ai/gemini-1.5-pro", None, "google/gemini-1.5-pro"),
    ("gemini/gemini-2.5-flash", "gemini", "google/gemini-2.5-flash"),
    ("openrouter/anthropic/claude-3.5-sonnet", "openrouter", "anthropic/claude-3.5-sonnet"),
    ("anthropic/claude-sonnet-4", None, "anthropic/claude-sonnet-4"),
    ("azure/gpt-4o", "azure", "openai/gpt-4o"),
    ("gpt-4o-2024-08-06", None, "openai/gpt-4o-2024-08-06"),
    ("o3-mini", None, "openai/o3-mini"),
    ("chatgpt-4o-latest", "openai", "openai/chatgpt-4o-latest"),
    ("GPT-5", None, "openai/gpt-5"),
    ("ollama/llama3:latest", "ollama", "meta/llama3"),
    ("groq/llama-3.1-70b-versatile", "groq", "meta/llama-3.1-70b-versatile"),
    ("meta-llama/Llama-3-70b", None, "meta/llama-3-70b"),
    ("together_ai/deepseek-ai/DeepSeek-V3", "together_ai", "deepseek/deepseek-ai/deepseek-v3"),
    ("deepseek-chat", "deepseek", "deepseek/deepseek-chat"),
    ("deepseek-v3", None, "deepseek/deepseek-v3"),
    ("qwen-max", None, "alibaba/qwen-max"),
    ("mistral/mistral-large-latest", "mistral", "mistral/mistral-large-latest"),
    ("codestral-2501", None, "mistral/codestral-2501"),
    ("xai/grok-3", "xai", "xai/grok-3"),
    ("openrouter/qwen/qwen3-coder:free", "openrouter", "alibaba/qwen3-coder"),
    ("acme-model-1", "acmecorp", "acmecorp/acme-model-1"),
    ("mystery-model", None, "unknown/mystery-model"),
    ("fireworks_ai/mystery-model", "fireworks_ai", "unknown/mystery-model"),
    ("  Claude-Opus-4-1  ", None, "anthropic/claude-opus-4-1"),
])
def test_canonical_model_id(raw, provider, expected):
    assert canonical_model_id(raw, provider) == expected


def test_date_snapshot_and_latest_stay_distinct():
    assert canonical_model_id("claude-3-5-sonnet-20241022") != canonical_model_id("claude-3-5-sonnet-latest")


@pytest.mark.parametrize("raw,expected", [
    ("high", "high"), ("HIGH", "high"), ("medium reasoning", "medium"), ("x-high", "xhigh"), ("xhigh", "xhigh"),
    ("minimal", "minimal"), ("low effort", "low"), ("4k thinking", "low"), ("16k thinking", "medium"),
    ("32k thinking", "high"), ("64k thinking", "xhigh"), ("thinking budget 8192 tokens", "medium"),
    ("thinking", None), ("default", None), ("", None), (None, None), ("3.7 thinking", None),
])
def test_normalize_effort(raw, expected):
    assert normalize_effort(raw) == expected


@pytest.mark.parametrize("display,expected", [
    ("Claude 4 Sonnet (32k thinking)", ("Claude 4 Sonnet", "high")),
    ("GPT-5 (medium reasoning)", ("GPT-5", "medium")),
    ("o3 (high)", ("o3", "high")),
    ("o4-mini-high", ("o4-mini", "high")),
    ("GPT-5 xhigh", ("GPT-5", "xhigh")),
    ("Claude 3.7 Sonnet (thinking)", ("Claude 3.7 Sonnet", None)),
    ("Claude 3.5 Sonnet (20241022)", ("Claude 3.5 Sonnet (20241022)", None)),
    ("Gemini 2.5 Pro", ("Gemini 2.5 Pro", None)),
])
def test_split_effort(display, expected):
    assert split_effort(display) == expected


KNOWN = {"anthropic/claude-3-5-sonnet-20241022", "anthropic/claude-3-5-sonnet-latest", "openai/gpt-5",
         "openai/gpt-5-mini", "google/gemini-2.5-pro", "alibaba/qwen3-coder", "acme/qwen3-coder"}


@pytest.mark.parametrize("display,expected", [
    ("GPT-5 (medium reasoning)", "openai/gpt-5"),
    ("gpt 5 mini", "openai/gpt-5-mini"),
    ("Gemini 2.5 Pro (32k thinking)", "google/gemini-2.5-pro"),
    ("Claude 3.5 Sonnet (20241022)", "anthropic/claude-3-5-sonnet-20241022"),
    ("Claude 3.5 Sonnet", None),             # date snapshot unknown: not guessed
    ("qwen3-coder", None),                   # two providers share the name: ambiguous
    ("Totally New Model", None),
    ("", None),
])
def test_resolve_benchmark_model(display, expected):
    assert resolve_benchmark_model(display, KNOWN) == expected


# --- risk.py: static estimate --------------------------------------------------------------------

def _skill(body="", policy="licensed", **kwargs):
    from tandem_catalog.contracts import Resource
    return Resource(item_id="r", type=kwargs.pop("type", "skill"), name="r", url="https://example.org",
                    body=body, body_policy=policy, **kwargs)


def test_metadata_only_without_commands_is_unknown_not_safe():
    from tandem_catalog.risk import scan
    result = scan(_skill(policy="metadata"))
    assert result["verdict"] == "unknown" and "body_not_read" in result["reasons"]
    assert scan(_skill("# Notes\nPlain advice only."))["verdict"] == "safe"


@pytest.mark.parametrize("body, flag", [
    ("Install:\n\n    curl https://x.sh | sh\n", "network"),            # indented code block
    ("~~~bash\necho hi\n~~~\n", "runs_command"),                       # tilde fence + shell info
    ("~~~\nrm -rf build/\n~~~\n", "destructive"),
    ("```bash\nrm -rf build/\n", "destructive"),                        # unclosed (truncated) fence
    ("````sh\n```\ngit push --force\n````\n", "destructive"),           # longer fence holds ``` inside
])
def test_code_blocks_of_every_markdown_form_are_scanned(body, flag):
    from tandem_catalog.risk import assess
    assert flag in assess(_skill(body))[0]


@pytest.mark.parametrize("body", [
    "Never run `rm -rf` on the repository root.",
    "Do not use git push --force on shared branches.",
    "```bash\n# never: rm -rf /\nls\n```",
    "A paragraph line\n    rm -rf continues the paragraph, not a code block",
])
def test_prose_warnings_and_comments_are_not_destructive(body):
    from tandem_catalog.risk import assess, scan
    flags, _ = assess(_skill(body))
    assert "destructive" not in flags
    assert scan(_skill(body))["verdict"] != "dangerous"


def test_declared_hook_command_is_dangerous():
    from tandem_catalog.risk import scan
    hook = _skill(policy="metadata", type="hook", install={"hook": {"event": "Stop", "command": "rm -rf .cache"}})
    assert scan(hook)["verdict"] == "dangerous"
