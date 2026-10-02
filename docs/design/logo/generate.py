"""生成 Tandem 莫比乌斯环 logo（SVG）。

构造：一条带子沿伯努利双纽线走一圈。起点在中心交叉处，带宽在这里收窄成尖（扭转时
侧边朝向观察者），走到对侧交叉处最宽、从下方穿过。颜色沿路径由深到浅渐变一整圈，
最深与最浅在收窄点相接——走一圈回到"另一面"，即莫比乌斯带的单侧性。

用法：python3 docs/design/logo/generate.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).parent

# 低饱和色：板岩灰 -> 鼠尾草灰 -> 雾灰，配合原型的暖纸底
STOPS = ("#5b676c", "#8d9a94", "#c9d0cb")
MONO = "#6f7b7d"
PAPER = "#f5f4f0"

A = 205  # 双纽线半长
W_MAX = 62  # 最大带宽
W_MIN = 1.5  # 收窄处带宽
EXPO = 0.55  # 带宽曲线，越小越早变宽
OVER = 0.06  # 中心上层段占整圈的比例（单侧）
GAP = 6  # 上层段与下层段之间的留白
N = 480  # 分段数


def mix(c0: str, c1: str, t: float) -> str:
    a = [int(c0[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def ramp(t: float) -> str:
    t *= len(STOPS) - 1
    i = min(int(t), len(STOPS) - 2)
    return mix(STOPS[i], STOPS[i + 1], t - i)


def curve(t: float) -> tuple[float, float]:
    d = 1 + math.sin(t) ** 2
    return A * math.cos(t) / d, A * math.sin(t) * math.cos(t) / d


def samples():
    """沿路径采样 (x, y, 法向 x, 法向 y, 带宽, 进度)。t0 = π/2 是中心交叉点。"""
    out = []
    for k in range(N + 1):
        s = k / N
        t = math.pi / 2 + 2 * math.pi * s
        x, y = curve(t)
        (x1, y1), (x2, y2) = curve(t - 1e-4), curve(t + 1e-4)
        L = math.hypot(x2 - x1, y2 - y1)
        w = W_MIN + (W_MAX - W_MIN) * abs(math.sin(math.pi * s)) ** EXPO
        out.append((x, y, -(y2 - y1) / L, (x2 - x1) / L, w, s))
    return out


def edges(a, b):
    ha, hb = a[4] / 2, b[4] / 2
    return [
        (a[0] + a[2] * ha, a[1] + a[3] * ha),
        (b[0] + b[2] * hb, b[1] + b[3] * hb),
        (b[0] - b[2] * hb, b[1] - b[3] * hb),
        (a[0] - a[2] * ha, a[1] - a[3] * ha),
    ]


def pts(q) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in q)


def body(mono: bool, bg: str) -> list[str]:
    p = samples()
    # 每片跨两步，相邻片重叠，避免抗锯齿接缝
    segs = []
    for k in range(N):
        a, b = p[k], p[min(k + 2, N)]
        d = min(a[5], 1 - a[5])
        segs.append((d < OVER, d < OVER * 0.6, edges(a, b), MONO if mono else ramp(a[5])))
    out = [f'<polygon points="{pts(q)}" fill="{c}"/>' for top, _, q, c in segs if not top]
    out += [
        f'<polygon points="{pts(q)}" fill="{bg}" stroke="{bg}" stroke-width="{GAP * 2}" stroke-linejoin="round"/>'
        for _, gap, q, _ in segs
        if gap
    ]
    out += [f'<polygon points="{pts(q)}" fill="{c}"/>' for top, _, q, c in segs if top]
    return out


def bbox(pad: float):
    xs, ys = [], []
    for a, b in zip(samples(), samples()[1:]):
        for x, y in edges(a, b):
            xs.append(x)
            ys.append(y)
    return min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad


def mark(mono: bool = False, gap_color: str = PAPER) -> str:
    """紧凑画布、透明底。中心留白用 gap_color 绘制，放在其他底色上时改成对应底色。"""
    x, y, w, h = bbox(4)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}" '
        f'width="{w:.0f}" height="{h:.0f}">{"".join(body(mono, gap_color))}</svg>\n'
    )


def icon(size: int = 1024) -> str:
    """方形图标：暖纸底圆角方块，标志居中。"""
    x, y, w, h = bbox(0)
    s = size * 0.78 / w
    tx, ty = size / 2 - (x + w / 2) * s, size / 2 - (y + h / 2) * s
    r = size * 0.225
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" rx="{r:.0f}" fill="{PAPER}"/>'
        f'<g transform="translate({tx:.1f} {ty:.1f}) scale({s:.4f})">{"".join(body(False, PAPER))}</g></svg>\n'
    )


def main():
    files = {
        "tandem-mark.svg": mark(),
        "tandem-mark-mono.svg": mark(mono=True),
        "tandem-icon.svg": icon(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text)
        print(f"{name}: {len(text) // 1024} KB")


if __name__ == "__main__":
    main()
