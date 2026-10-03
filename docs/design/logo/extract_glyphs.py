"""从开源字体提取字标「Orbit·知音」中 rbit 与知音的字形轮廓，写入 wordmark-glyphs.json（generate.py 只读这个文件，不依赖字体或 fontTools）。

字体与字重来自 orbit-spec.json 的 wordmark.fonts（latin：rbit 与量竖干宽用的 l；cjk：知音）；字体文件从 google/fonts 下载并记录 SHA-256。TrueType 的二次曲线
按精确公式升为三次贝塞尔，坐标为字体单位（y 向上）。换字体或字重时运行：

  uv run --no-project --with fonttools python docs/design/logo/extract_glyphs.py
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).parent


class CubicPen(BasePen):
    """记录轮廓为三次贝塞尔段 [p0, p1, p2, p3]。"""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.contours, self._cur, self._start = [], [], None

    def _moveTo(self, p):
        self._start, self._cur = p, []

    def _lineTo(self, p):
        a = self._getCurrentPoint()
        self._cur.append([a, (a[0] + (p[0] - a[0]) / 3, a[1] + (p[1] - a[1]) / 3),
                          (a[0] + 2 * (p[0] - a[0]) / 3, a[1] + 2 * (p[1] - a[1]) / 3), p])

    def _curveToOne(self, p1, p2, p3):
        self._cur.append([self._getCurrentPoint(), p1, p2, p3])

    def _qCurveToOne(self, q, p):
        a = self._getCurrentPoint()
        self._cur.append([a, (a[0] + 2 / 3 * (q[0] - a[0]), a[1] + 2 / 3 * (q[1] - a[1])),
                          (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1])), p])

    def _closePath(self):
        a = self._getCurrentPoint()
        if a != self._start:
            self._lineTo(self._start)
        if self._cur:
            self.contours.append([[[round(v, 2) for v in q] for q in seg] for seg in self._cur])
        self._cur = []

    _endPath = _closePath


def extract(spec: dict, chars: str) -> dict:
    raw = urllib.request.urlopen(spec["source"]).read()
    font = TTFont(io.BytesIO(raw))
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": spec["weight"]}, inplace=False)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    glyphs = {}
    for ch in chars:
        g = gs[cmap[ord(ch)]]
        pen, box = CubicPen(gs), BoundsPen(gs)
        g.draw(pen)
        g.draw(box)
        glyphs[ch] = {"advance": g.width, "bounds": [round(v, 2) for v in box.bounds], "contours": pen.contours}
    return {
        "family": spec["family"], "weight": spec["weight"], "source": spec["source"],
        "sha256": hashlib.sha256(raw).hexdigest(), "license": "SIL Open Font License 1.1",
        "units_per_em": font["head"].unitsPerEm, "glyphs": glyphs,
    }


def main() -> None:
    fonts = json.loads((ROOT / "orbit-spec.json").read_text(encoding="utf-8"))["wordmark"]["fonts"]
    out = {"latin": extract(fonts["latin"], "rbitl"), "cjk": extract(fonts["cjk"], "知音")}
    (ROOT / "wordmark-glyphs.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    for k, v in out.items():
        print(f"{k}: {v['family']} {v['weight']}, {sum(len(g['contours']) for g in v['glyphs'].values())} contours")


if __name__ == "__main__":
    main()
