"""Static checks of the native shell's menu (apps/desktop/Orbit.swift): no key equivalent twice.

The menu is built in code, so this reads every item that sets a key equivalent:
``command("…", "cmd", key: "k", mods: [...])`` helpers and ``addItem(withTitle:…, keyEquivalent: "k")``
calls (optionally followed by ``<var>.keyEquivalentModifierMask = [...]``). An item without an
explicit mask has AppKit's default, ⌘ alone.
"""

from __future__ import annotations

import re
from pathlib import Path

SWIFT = Path(__file__).resolve().parents[2] / "apps/desktop/Orbit.swift"

COMMAND = re.compile(r'command\("([^"]+)",\s*"[^"]+"(?:,\s*key:\s*"([^"]*)")?(?:,\s*mods:\s*\[([^\]]*)\])?')
ADD = re.compile(
    r'(?:let\s+(\w+)\s*=\s*)?\w+\.addItem\(withTitle:\s*"([^"]+)"[^\n]*?keyEquivalent:\s*"([^"]*)"\)'
)
MASK = re.compile(r"(\w+)\.keyEquivalentModifierMask\s*=\s*\[([^\]]*)\]")


def _mods(raw: str | None) -> frozenset[str]:
    if raw is None:
        return frozenset({"command"})
    return frozenset(m.strip().lstrip(".") for m in raw.split(",") if m.strip())


def menu_shortcuts(source: str) -> list[tuple[str, str, frozenset[str]]]:
    body = source[source.index("func buildMenu()") : source.index("func command(")]
    masks = {m.group(1): m.group(2) for m in MASK.finditer(body)}
    items: list[tuple[str, str, frozenset[str]]] = []
    for m in COMMAND.finditer(body):
        if m.group(2):
            items.append((m.group(1), m.group(2).lower(), _mods(m.group(3))))
    for m in ADD.finditer(body):
        var, title, key = m.group(1), m.group(2), m.group(3)
        if key:
            items.append((title, key.lower(), _mods(masks.get(var) if var else None)))
    return items


def test_menu_shortcuts_are_unique() -> None:
    items = menu_shortcuts(SWIFT.read_text(encoding="utf-8"))
    assert len(items) > 15, items  # the parser still sees the menu
    seen: dict[tuple[str, frozenset[str]], str] = {}
    for title, key, mods in items:
        combo = (key, mods)
        assert combo not in seen, f"{title} and {seen[combo]} share {sorted(mods)}+{key}"
        seen[combo] = title


def test_hud_and_widgets_keys_match_the_page() -> None:
    items = {title: (key, mods) for title, key, mods in menu_shortcuts(SWIFT.read_text("utf-8"))}
    assert items["显示 HUD"] == ("p", frozenset({"command", "option"}))  # 85-keyboard.js ⌥⌘P
    assert items["桌面小组件"] == ("d", frozenset({"command", "option"}))
    assert items["隐藏其他"] == ("h", frozenset({"command", "option"}))
