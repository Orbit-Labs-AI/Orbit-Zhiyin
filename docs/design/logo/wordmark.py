"""Orbit 字标：首字母 O 是同一条螺旋在俯视视角（o_pitch）下的投影，后接衬线小写 rbit。

rbit 的字形来自开源字体（orbit-spec.json 的 wordmark.font，轮廓由 extract_glyphs.py 写入 wordmark-glyphs.json），
这里只做等比缩放与排列，因此字形本身不重画。长度以「字高」H（O 的墨迹高度去掉上下视觉溢出）为单位：
b 的升部顶与字高对齐，O 与 r 的墨迹间距为 spacing.O_r，其后按字体自身的步进宽度排列，另加 tracking。

坐标与标志的设计坐标相同（y 向下）：基线 = O 墨迹底边 − 溢出，字高顶 = O 墨迹顶边 + 溢出。
"""

from __future__ import annotations

import json
from pathlib import Path

from orbit import num

ROOT = Path(__file__).parent


class Wordmark:
    def __init__(self, spec: dict, mark_ink: tuple[float, float, float, float]):
        p = spec["wordmark"]
        data = json.loads((ROOT / p["font"]["glyphs"]).read_text(encoding="utf-8"))
        if (data["family"], data["weight"]) != (p["font"]["family"], p["font"]["weight"]):
            raise SystemExit("wordmark-glyphs.json 与 orbit-spec.json 的字体不一致：运行 extract_glyphs.py")
        x0, y0, x1, y1 = mark_ink  # O 的墨迹外框（设计坐标）
        over = p["overshoot"] * (y1 - y0)
        self.base, top = y1 - over, y0 + over
        H = self.base - top
        g = data["glyphs"]
        s = p["ascender"] * H / g["b"]["bounds"][3]  # 字体单位 → 设计单位
        x = x1 + p["spacing"]["O_r"] * H - g["r"]["bounds"][0] * s
        self.letters, right, low = {}, x1, y1
        for ch in "rbit":
            ox = x
            self.letters[ch] = [
                [tuple((ox + q[0] * s, self.base - q[1] * s) for q in seg) for seg in contour] for contour in g[ch]["contours"]
            ]
            right = ox + g[ch]["bounds"][2] * s
            low = max(low, self.base - g[ch]["bounds"][1] * s)
            x += g[ch]["advance"] * s + p["tracking"] * H
        self.contours = [c for ch in "rbit" for c in self.letters[ch]]
        self.box = (x0, min(y0, self.base - p["ascender"] * H), right, low)
        self.cap_height, self.x_height = H, data["x_height"] * s

    def path(self, digits: int = 3, letters: str = "rbit") -> str:
        f = lambda q: f"{num(q[0], digits)} {num(q[1], digits)}"  # noqa: E731
        cs = [c for ch in letters for c in self.letters[ch]]
        return "".join("M" + f(c[0][0]) + "".join("C" + " ".join(f(q) for q in seg[1:]) for seg in c) + "Z" for c in cs)
