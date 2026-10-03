"""Orbit 字标「Orbit·知音」：O 是同一条螺旋在俯视视角（o_pitch）下的投影，后接 rbit、间隔圆点与知音。

rbit 与知音的字形来自开源字体（orbit-spec.json 的 wordmark.fonts，轮廓由 extract_glyphs.py 写入 wordmark-glyphs.json），
这里只做等比缩放与排列，字形本身不重画。长度以「字高」H（O 的墨迹高度去掉上下视觉溢出）为单位：
- rbit：b 的升部顶与字高对齐，O 与 r 的墨迹间距 spacing.O_r，其后按字体步进宽度排列（另加 tracking）；
- 间隔点：圆点，直径 = l 竖干宽 × dot.diameter，圆心在字高中线，与 t、知的墨迹间距 spacing.t_dot / dot_cjk；
- 知音：墨迹高度 = H × cjk.height，垂直中心在字高中线，按字体步进宽度排列。

坐标与标志的设计坐标相同（y 向下）：基线 = O 墨迹底边 − 溢出，字高顶 = O 墨迹顶边 + 溢出。
"""

from __future__ import annotations

import json
from pathlib import Path

from orbit import KAPPA, num

ROOT = Path(__file__).parent
TEXT = "rbit·知音"  # O 之后的字符，也是动效里依次出现的顺序


def _place(contours, s: float, x: float, y: float):
    """字体单位（y 向上）→ 设计坐标（y 向下）。"""
    return [[tuple((x + q[0] * s, y - q[1] * s) for q in seg) for seg in c] for c in contours]


def _disc(cx: float, cy: float, r: float):
    k = KAPPA * r
    pts = [(cx - r, cy), (cx, cy - r), (cx + r, cy), (cx, cy + r)]
    hs = [((0, -k), (-k, 0)), ((k, 0), (0, -k)), ((0, k), (k, 0)), ((-k, 0), (0, k))]
    return [[[pts[i], (pts[i][0] + hs[i][0][0], pts[i][1] + hs[i][0][1]),
              (pts[(i + 1) % 4][0] + hs[i][1][0], pts[(i + 1) % 4][1] + hs[i][1][1]), pts[(i + 1) % 4]] for i in range(4)]]


class Wordmark:
    def __init__(self, spec: dict, mark_ink: tuple[float, float, float, float]):
        p = spec["wordmark"]
        data = json.loads((ROOT / p["glyphs"]).read_text(encoding="utf-8"))
        for key in ("latin", "cjk"):
            if (data[key]["family"], data[key]["weight"]) != (p["fonts"][key]["family"], p["fonts"][key]["weight"]):
                raise SystemExit("wordmark-glyphs.json 与 orbit-spec.json 的字体不一致：运行 extract_glyphs.py")
        x0, y0, x1, y1 = mark_ink  # O 的墨迹外框（设计坐标）
        over = p["overshoot"] * (y1 - y0)
        self.base, top = y1 - over, y0 + over
        H = self.base - top
        mid = self.base - H / 2
        sp = p["spacing"]
        self.letters = {}

        lat = data["latin"]["glyphs"]
        s = p["ascender"] * H / lat["b"]["bounds"][3]
        x = x1 + sp["O_r"] * H - lat["r"]["bounds"][0] * s
        for ch in "rbit":
            self.letters[ch] = _place(lat[ch]["contours"], s, x, self.base)
            right = x + lat[ch]["bounds"][2] * s
            x += lat[ch]["advance"] * s + p["tracking"] * H
        self.x_height = None

        lb = lat["l"]["bounds"]
        r = (lb[2] - lb[0]) * s * p["dot"]["diameter"] / 2
        cx = right + sp["t_dot"] * H + r
        self.letters["·"] = _disc(cx, mid, r)
        right = cx + r

        cjk = data["cjk"]["glyphs"]
        lo = min(cjk[ch]["bounds"][1] for ch in "知音")
        hi = max(cjk[ch]["bounds"][3] for ch in "知音")
        s2 = p["cjk"]["height"] * H / (hi - lo)
        y = mid + (lo + hi) / 2 * s2  # 字体基线位置：使知音墨迹的垂直中心落在字高中线
        x = right + sp["dot_cjk"] * H - cjk["知"]["bounds"][0] * s2
        for ch in "知音":
            self.letters[ch] = _place(cjk[ch]["contours"], s2, x, y)
            right = x + cjk[ch]["bounds"][2] * s2
            x += cjk[ch]["advance"] * s2

        self.contours = [c for ch in TEXT for c in self.letters[ch]]
        low = max(y1, self.base - min(lat[ch]["bounds"][1] for ch in "rbit") * s, y - lo * s2)
        self.box = (x0, min(y0, self.base - p["ascender"] * H), right, low)
        self.cap_height = H

    def path(self, digits: int = 3, letters: str = TEXT) -> str:
        f = lambda q: f"{num(q[0], digits)} {num(q[1], digits)}"  # noqa: E731
        cs = [c for ch in letters for c in self.letters[ch]]
        return "".join("M" + f(c[0][0]) + "".join("C" + " ".join(f(q) for q in seg[1:]) for seg in c) + "Z" for c in cs)
