"""Orbit 字标：首字母 O 是同一条螺旋在俯视视角（o_pitch）下的投影，后接几何单线小写 rbit。

参数全部来自 orbit-spec.json 的 wordmark 一节，长度以「字高」H（标志墨迹高度去掉上下视觉溢出）为单位，
线宽以设计单位给出。字母由直线段与圆弧组成，均按圆头单线描边后展开成填充轮廓（三次贝塞尔），
因此与标志一样是纯填充矢量，放大缩小只做等比变换。

坐标与标志的设计坐标相同（y 向下）：基线 = 标志墨迹底边 − 溢出，字高顶 = 标志墨迹顶边 + 溢出。
"""

from __future__ import annotations

import math

from orbit import num


def _arc(cx, cy, r, a0, a1):
    """圆弧（角度为弧度，y 向下时角度增大即顺时针）→ 三次贝塞尔段列表，每段不超过 90°。"""
    n = max(1, math.ceil(abs(a1 - a0) / (math.pi / 2) - 1e-9))
    out, step = [], (a1 - a0) / n
    k = 4 / 3 * math.tan(step / 4)
    for i in range(n):
        s, e = a0 + i * step, a0 + (i + 1) * step
        p0 = (cx + r * math.cos(s), cy + r * math.sin(s))
        p3 = (cx + r * math.cos(e), cy + r * math.sin(e))
        p1 = (p0[0] - k * r * math.sin(s), p0[1] + k * r * math.cos(s))
        p2 = (p3[0] + k * r * math.sin(e), p3[1] - k * r * math.cos(e))
        out.append((p0, p1, p2, p3))
    return out


def _line(a, b):
    return [(a, (a[0] + (b[0] - a[0]) / 3, a[1] + (b[1] - a[1]) / 3), (a[0] + 2 * (b[0] - a[0]) / 3, a[1] + 2 * (b[1] - a[1]) / 3), b)]


def _area(segs):
    """有向面积（用控制多边形近似，只取符号）。"""
    pts = [q for s in segs for q in s[:3]]
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2


def _orient(segs, positive=True):
    if (_area(segs) > 0) != positive:
        segs = [(d, c, b, a) for a, b, c, d in reversed(segs)]
    return segs


def capsule(a, b, w):
    """线段 ab 的圆头描边轮廓。"""
    h = w / 2
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    nx, ny = -math.sin(ang), math.cos(ang)
    segs = _line((a[0] + nx * h, a[1] + ny * h), (b[0] + nx * h, b[1] + ny * h))
    segs += _arc(b[0], b[1], h, ang + math.pi / 2, ang - math.pi / 2)
    segs += _line((b[0] - nx * h, b[1] - ny * h), (a[0] - nx * h, a[1] - ny * h))
    segs += _arc(a[0], a[1], h, ang - math.pi / 2, ang - 3 * math.pi / 2)
    return [_orient(segs)]


def arc_band(c, r, a0, a1, w):
    """圆心 c、中心线半径 r、从 a0 到 a1（a1 > a0）的圆头描边轮廓。"""
    h = w / 2
    pe = (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1))
    ps = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
    segs = _arc(c[0], c[1], r + h, a0, a1)
    segs += _arc(pe[0], pe[1], h, a1, a1 + math.pi)
    segs += _arc(c[0], c[1], r - h, a1, a0)
    segs += _arc(ps[0], ps[1], h, a0 + math.pi, a0 + 2 * math.pi)
    return [_orient(segs)]


def ring(c, r, w):
    h = w / 2
    return [_orient(_arc(c[0], c[1], r + h, 0, 2 * math.pi)), _orient(_arc(c[0], c[1], r - h, 0, 2 * math.pi), False)]


def disc(c, r):
    return [_orient(_arc(c[0], c[1], r, 0, 2 * math.pi))]


class Wordmark:
    def __init__(self, spec: dict, mark_ink: tuple[float, float, float, float]):
        p = spec["wordmark"]
        x0, y0, x1, y1 = mark_ink  # 标志墨迹外框（设计坐标）
        over = p["overshoot"] * (y1 - y0)
        self.base, top = y1 - over, y0 + over
        H = self.base - top
        w = p["stroke"]
        h = w / 2
        xh, asc, th = p["x_height"] * H, p["ascender"] * H, p["t_height"] * H
        sp = {k: v * H for k, v in p["spacing"].items()}
        base, xtop = self.base, self.base - xh
        contours, self.letters = [], {}

        # r：竖干 + 肩部圆弧
        x = x1 + sp["O_r"] + h
        rr = p["r_shoulder"] * xh
        contours += capsule((x, xtop + h), (x, base - h), w)
        ca = (x + rr, xtop + h + rr)
        contours += arc_band(ca, rr, math.pi, math.radians(p["r_arm_end"]), w)
        right = max(x + h, ca[0] + (rr + h) * math.cos(math.radians(p["r_arm_end"])))
        self.letters["r"], mark = contours[:], len(contours)
        # b：升部竖干 + 整圆碗
        x = right + sp["r_b"] + h
        rb = (xh - w) / 2
        contours += capsule((x, base - asc + h), (x, base - h), w)
        cb = (x + rb, base - xh / 2)
        contours += ring(cb, rb, w)
        right = cb[0] + rb + h
        self.letters["b"], mark = contours[mark:], len(contours)
        # i：竖干 + 圆点
        x = right + sp["b_i"] + h
        contours += capsule((x, xtop + h), (x, base - h), w)
        dot = p["i_dot"] * w / 2
        contours += disc((x, xtop - p["i_dot_gap"] * H - dot), dot)
        right = x + max(h, dot)
        self.letters["i"], mark = contours[mark:], len(contours)
        # t：竖干 + 横笔（以竖干为中心）+ 底部圆弧收尾（t_hook = 圆弧半径 × x 字高，0 为直干）
        x = right + sp["i_t"] + p["t_bar"] * xh / 2
        bar = p["t_bar"] * xh / 2
        hook = p.get("t_hook", 0) * xh
        if hook:
            ct = (x + hook, base - h - hook)
            contours += capsule((x, base - th + h), (x, ct[1]), w)
            end = math.radians(p.get("t_hook_end", 60))
            contours += arc_band(ct, hook, end, math.pi, w)
            right = max(x + bar, ct[0] + hook * math.cos(end) + h)
        else:
            contours += capsule((x, base - th + h), (x, base - h), w)
            right = x + bar
        contours += capsule((x - bar + h, xtop + h), (x + bar - h, xtop + h), w)
        self.letters["t"] = contours[mark:]

        self.contours = contours
        self.box = (x0, min(y0, base - asc), right, max(y1, base))
        self.cap_height, self.x_height = H, xh

    def path(self, digits: int = 3, letters: str = "rbit") -> str:
        f = lambda q: f"{num(q[0], digits)} {num(q[1], digits)}"  # noqa: E731
        cs = [c for ch in letters for c in self.letters[ch]]
        return "".join("M" + f(s[0][0]) + "".join("C" + " ".join(f(q) for q in seg[1:]) for seg in s) + "Z" for s in cs)
