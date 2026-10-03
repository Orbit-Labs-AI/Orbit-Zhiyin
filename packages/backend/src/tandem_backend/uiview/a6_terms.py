"""A6「高频词」: everyday words in the user's own messages, for the word cloud on ``/v1/uiview/sentiment``.

Input is the confirmed human text the A6 adapter already reads (``v_human_message`` after
``direct_user_text``: code fences, block quotes and platform blocks removed; inline code and
quotations stripped by ``semantic_text``). Agent replies and tool output never reach this module.

Each message is washed with the active redaction rules (``privacy_rules.apply``, ingest + outbound)
before it is split, and every placeholder the rules leave is dropped, so a redacted value never
becomes a word. Chinese is cut with the fixed private jieba dictionary of ``products.lexical``;
English is kept as whole words. Dropped outright: URLs, paths, e-mail, code identifiers
(snake_case, camelCase, dotted names, flags, anything with code punctuation), version / id strings
mixing digits and letters, secret-like strings, pure numbers, stop words and words that are too short.
A long message pasted verbatim several times counts once, so a template cannot fill the cloud.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

TERMS_VERSION = "a6-terms-v1"
TERMS_LIMIT = 60
TEMPLATE_MIN_CHARS = 40  # a message at least this long, repeated verbatim, counts once
LATIN_MIN, LATIN_MAX, CJK_MIN, CJK_MAX = 2, 24, 2, 8

# Placeholders the redaction rules write ([密钥已隐藏], [email], [user], <redacted…> …) and "~" for home.
_PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,40}\]|<redacted[^>]*>|(?<!\S)~(?=/|\s|$)", re.I)
_URL = re.compile(r"(?:\b[a-z][a-z0-9+.-]{1,15}://|\bwww\.)\S+", re.I)
_EMAIL = re.compile(r"\S+@\S+\.\S+")
# Runs of non-space ASCII and runs of CJK are judged separately: Chinese has no spaces, so
# "修一下foo_bar的bug" must still drop foo_bar and keep 修一下 / bug.
_CHUNK = re.compile(r"[㐀-䶿一-鿿豈-﫿]+|[\x21-\x7e]+")
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
_CODE_PUNCT = re.compile(r"[_/\\=<>{}\[\]$@#^|*`~]|::|->|=>|\(\)|\w\.\w|^--?\w|^\.\w")
_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]{2,}")
_ALNUM_MIX = re.compile(r"(?=[^\s]*[A-Za-z])(?=[^\s]*\d)")
_HEXISH = re.compile(r"^[0-9a-f]{12,}$", re.I)
_SECRET = re.compile(r"^(?:sk|pk|rk|gh[pousr]|github_pat|xox[abpr]|akia|ya29|eyJ)[-_A-Za-z0-9]*$", re.I)

STOP_ZH = frozenset("""
的 了 和 是 在 我 你 他 她 它 我们 你们 他们 她们 它们 咱们 自己 这 那 这个 那个 这些 那些 这样 那样 这里 那里 这边 那边
这种 那种 一个 一些 一下 一点 一样 一直 一起 一种 有点 有些 什么 怎么 怎样 怎么样 为什么 哪个 哪些 哪里 多少 如何
就是 还是 或者 而且 但是 不过 然后 所以 因为 如果 虽然 只是 还有 以及 并且 或是 及其 即可 可以 可能 能够 应该 需要
要是 就要 已经 正在 现在 之前 之后 以后 以前 时候 的话 还要 不要 不是 没有 不会 不能 是否 是不是 有没有 好的 好吧
请问 一般 比较 非常 特别 其实 真的 那么 这么 一下子 东西 地方 问题 情况 方面 部分 进行 当前 目前 相关 对于 关于
通过 根据 按照 为了 以便 其中 其他 另外 而是 然而 于是 因此 并不 并非 吗 呢 吧 啊 呀 哦 嗯 哈 么 嘛 啦 喔
帮我 给我 让我 我想 我要 你们 您 请 把 被 让 给 从 向 对 到 跟 与 及 等 着 过 也 都 又 就 才 还 很 太 更 最 再
""".split())
STOP_EN = frozenset("""
a about above after again against all also am an and any are aren't as at be because been before being below between both
but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each else ever few for from
further get gets got had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself
his how how's however i i'd i'll i'm i've if in into is isn't it it's its itself just let let's lets like may me might
more most much must mustn't my myself no nor not now of off on once only or other ought our ours ourselves out over own
please pls same shall shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs them
themselves then there there's these they they'd they'll they're they've thing things this those though through thus to
too under until up upon us very via was wasn't we we'd we'll we're we've were weren't what what's when when's where
where's whether which while who who's whom whose why why's will with within without won't would wouldn't yet you you'd
you'll you're you've your yours yourself yourselves ok okay yeah yep yes hi hey hello thanks thank um uh hmm etc eg ie
""".split())


def _clean(text: str, config: dict | None) -> str:
    from ..privacy_rules import rules

    washed, _ = rules.apply(text or "", config, stages=("ingest", "outbound"))
    washed = unicodedata.normalize("NFKC", washed)
    return _EMAIL.sub(" ", _URL.sub(" ", _PLACEHOLDER.sub(" ", washed)))


def _latin_ok(chunk: str) -> bool:
    """False for a whole ASCII run that is code, a path, an id / version or a secret."""
    core = chunk.strip(".,;:!?\"'()[]{}<>，。")
    if not core:
        return False
    if _CODE_PUNCT.search(core) or _CAMEL.search(core) or _SECRET.match(core) or _HEXISH.match(core):
        return False
    return not _ALNUM_MIX.match(core)


def words(text: str, config: dict | None = None) -> list[str]:
    """Display-ready words of one human message, in order (duplicates kept)."""
    from ..analytics.products.lexical import tokenizer

    out: list[str] = []
    for chunk in _CHUNK.findall(_clean(text, config)):
        if _CJK.match(chunk):
            for w in tokenizer().cut(chunk, HMM=False):
                if CJK_MIN <= len(w) <= CJK_MAX and _CJK.search(w) and w not in STOP_ZH:
                    out.append(w)
            continue
        if not _latin_ok(chunk):
            continue
        for w in _WORD.findall(chunk):
            w = w.casefold()
            if LATIN_MIN <= len(w) <= LATIN_MAX and w not in STOP_EN:
                out.append(w)
    return out


def _day(ts, zone) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone).date().isoformat()


def build_terms(humans, sessions, zone, *, limit: int = TERMS_LIMIT, config: dict | None = None) -> dict:
    """Top ``limit`` words: ``{items: [{term, count, days, sessions, share}], n_messages, n_tokens, …}``.

    ``count`` = occurrences, ``days`` = distinct local dates the word was used on, ``share`` =
    count / all kept word occurrences. Empty input gives ``items: []``.
    """
    if config is None:
        from ..privacy_rules import rules

        config = rules.current()
    counts: Counter = Counter()
    days: dict[str, set] = defaultdict(set)
    sess: dict[str, set] = defaultdict(set)
    seen_long: set[str] = set()
    used = 0
    for m in humans:
        text = m.get("text") or ""
        if not text.strip():
            continue
        key = " ".join(text.casefold().split())
        if len(key) >= TEMPLATE_MIN_CHARS:
            if key in seen_long:
                continue
            seen_long.add(key)
        ws = words(text, config)
        if not ws:
            continue
        used += 1
        session = sessions.get(m["session_uid"]) or {}
        day = _day(m.get("ts") if m.get("ts") is not None else session.get("started_at"), zone)
        for w in ws:
            counts[w] += 1
            if day:
                days[w].add(day)
            sess[w].add(m["session_uid"])
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda kv: (-kv[1], -len(days[kv[0]]), kv[0]))[:limit]
    return {"items": [{"term": t, "count": n, "days": len(days[t]), "sessions": len(sess[t]),
                       "share": round(n / total, 4)} for t, n in top],
            "n_messages": used, "n_tokens": total, "limit": limit,
            "version": TERMS_VERSION, "method": "jieba(fixed dict)+english words; redacted; stop words removed"}
