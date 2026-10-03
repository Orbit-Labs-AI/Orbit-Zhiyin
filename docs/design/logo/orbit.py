"""Orbit 标志的矢量几何（纯 Python，无第三方依赖）。

参数全部来自 orbit-spec.json。计算链：

1. 锥形螺旋 P(t) = (r cos θ, r sin θ, rise·t)，θ = 2π·turns·t + phase，r = r_start + (r_end − r_start)·t，t ∈ [0, 1]；
2. 绕 z 轴转 yaw、绕 x 轴转 pitch 后正交投影，得到屏幕中心线 S(t) 与深度 D(t)（越大越近）；
   按 3001 个取样点的外框把中心线等比缩放进边长 size、留白 pad 的设计坐标；
3. 线宽 w(t) = max(w_floor, (w_far + (w_near − w_far)·(D − D_min)/(D_max − D_min))·sin(e·π/2))，
   e = min(1, L/(taper·T), (T − L)/(taper·T))，L 为屏幕弧长、T 为全长：近粗远细，两端渐细；
4. 投影交叉处较远的一支沿弧长两侧各断开 gap/2 + 该处线宽；
5. 每段两侧轮廓 S(t) ± n(t)·w(t)/2（n 为左法线）用三次贝塞尔分段拟合，误差不超过 vector.tolerance，
   段端为半圆圆头。整条标志输出为一条 SVG path（设计坐标）。

第一版标志（v1）是折线多边形：中心线按屏幕弧长每 resample 取一点，末端、深度范围与断口都落在取样点上。
`_resolve_v1` 按 v1 的离散算法求出这些常数（取样终点、深度范围、断口区间、标志外框与图标变换），
矢量轮廓沿用它们，因此与 v1 逐点重合，只是把折线换成了平滑曲线。
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).parent
SPEC = ROOT / "orbit-spec.json"

GAUSS = (  # 5 点 Gauss-Legendre（区间 [-1, 1]）
    (-0.906179845938664, 0.2369268850561891),
    (-0.5384693101056831, 0.4786286704993665),
    (0.0, 0.5688888888888889),
    (0.5384693101056831, 0.4786286704993665),
    (0.906179845938664, 0.2369268850561891),
)
KAPPA = 0.5522847498307936  # 四分之一圆弧的三次贝塞尔控制柄长度 / 半径


def load_spec(path: Path = SPEC) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def num(v: float, digits: int = 3) -> str:
    """定点小数，去掉末尾的 0。"""
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Orbit:
    def __init__(self, spec: dict):
        self.spec = spec
        c, v, d, s, vec = spec["curve"], spec["view"], spec["design"], spec["stroke"], spec["vector"]
        self.turns, self.r0, self.r1 = c["turns"], c["r_start"], c["r_end"]
        self.rise, self.phase, self.m = c["rise"], c["phase"], c["samples"]
        yaw, pitch = math.radians(v["yaw"]), math.radians(v["pitch"])
        self._rot = (math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch))
        self.size, self.pad, self.step, self.box_pad = d["size"], d["pad"], d["resample"], d["box_pad"]
        self.w_far, self.w_near, self.taper = s["w_far"], s["w_near"], s["taper"]
        self.w_floor, self.gap = s["w_floor"], s["gap"]
        self.tol, self.digits = vec["tolerance"], vec["digits"]
        self._fit_view()
        self._resolve_v1()
        self._arc_table()

    # ---- 中心线 -------------------------------------------------------------------------------------

    def _space(self, t: float):
        """螺旋上的点及其一、二阶导数（三维）。"""
        w = 2 * math.pi * self.turns
        th = w * t + self.phase
        r = self.r0 + (self.r1 - self.r0) * t
        dr = self.r1 - self.r0
        c, s = math.cos(th), math.sin(th)
        p = (r * c, r * s, self.rise * t)
        d1 = (dr * c - r * s * w, dr * s + r * c * w, self.rise)
        d2 = (-2 * dr * s * w - r * c * w * w, 2 * dr * c * w - r * s * w * w, 0.0)
        return p, d1, d2

    def _project(self, x: float, y: float, z: float):
        """旋转后正交投影：(屏幕 x, 屏幕 y, 深度)。线性变换，导数同样适用。"""
        cy, sy, cp, sp = self._rot
        x1, y1 = x * cy - y * sy, x * sy + y * cy
        y2, z2 = y1 * cp - z * sp, y1 * sp + z * cp
        return x1, -z2, -y2

    def _fit_view(self) -> None:
        pts = [self._project(*self._space(k / self.m)[0]) for k in range(self.m + 1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        fit = self.spec["view"].get("fit")  # 动效帧：沿用给定的缩放与中心（绕轴旋转时大小不随朝向跳动）
        if fit:
            self.scale, self.cx, self.cy = fit
        else:
            self.scale = (self.size - 2 * self.pad) / max(max(xs) - min(xs), max(ys) - min(ys))
            self.cx, self.cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        h = self.size / 2
        self._samples = [(h + (x - self.cx) * self.scale, h + (y - self.cy) * self.scale, z) for x, y, z in pts]

    def point(self, t: float):
        """屏幕中心线 S、S'、S''，深度 D 与 D'。"""
        p, d1, d2 = self._space(t)
        x, y, z = self._project(*p)
        dx, dy, dz = self._project(*d1)
        ex, ey, _ = self._project(*d2)
        k, h = self.scale, self.size / 2
        return (h + (x - self.cx) * k, h + (y - self.cy) * k), (dx * k, dy * k), (ex * k, ey * k), z, dz

    # ---- v1 的离散常数 ------------------------------------------------------------------------------

    def _resolve_v1(self) -> None:
        smp = self._samples
        kept, acc = [0], 0.0
        for k in range(1, len(smp)):
            acc += math.dist(smp[k][:2], smp[k - 1][:2])
            if acc >= self.step:
                kept.append(k)
                acc = 0.0
        p = [smp[k] for k in kept]
        n = len(p)
        length = [0.0]
        for i in range(1, n):
            length.append(length[-1] + math.dist(p[i][:2], p[i - 1][:2]))
        total = length[-1]
        z0, z1 = min(q[2] for q in p), max(q[2] for q in p)

        def width(k):
            e = min(1.0, length[k] / (total * self.taper), (total - length[k]) / (total * self.taper))
            lin = self.w_far + (self.w_near - self.w_far) * (p[k][2] - z0) / (z1 - z0)
            return max(self.w_floor, lin * math.sin(e * math.pi / 2))

        w = [width(k) for k in range(n)]
        far = []
        for i in range(n - 1):
            a, b = p[i], p[i + 1]
            for j in range(i + 3, n - 1):
                c, d = p[j], p[j + 1]
                if max(c[0], d[0]) < min(a[0], b[0]) or min(c[0], d[0]) > max(a[0], b[0]):
                    continue
                if max(c[1], d[1]) < min(a[1], b[1]) or min(c[1], d[1]) > max(a[1], b[1]):
                    continue
                den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
                if abs(den) < 1e-12:
                    continue
                u = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den
                v = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / den
                if 0 <= u < 1 and 0 <= v < 1:
                    za, zc = a[2] + u * (b[2] - a[2]), c[2] + v * (d[2] - c[2])
                    far.append((i if za < zc else j, i, j, u, v))
        cut = [False] * n
        for f, *_ in far:
            r = self.gap / 2 + w[f]
            for k in range(n):
                if abs(length[k] - length[f]) < r:
                    cut[k] = True
        runs, cur = [], []
        for k in range(n):
            if cut[k]:
                if len(cur) > 1:
                    runs.append(cur)
                cur = []
            else:
                cur.append(k)
        if len(cur) > 1:
            runs.append(cur)

        edges, self._v1_edges = [], {}
        for run in runs:
            for k in run:
                a, b = p[max(0, k - 1)], p[min(n - 1, k + 1)]
                ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                nx, ny, h = -(b[1] - a[1]) / ln, (b[0] - a[0]) / ln, w[k] / 2
                left, right = (p[k][0] + nx * h, p[k][1] + ny * h), (p[k][0] - nx * h, p[k][1] - ny * h)
                edges += [left, right]
                self._v1_edges[kept[k]] = (left, right)
        xs, ys = [x for x, _ in edges], [y for _, y in edges]
        pad = self.box_pad
        self.box = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)

        self.t_end = kept[-1] / self.m
        self.z0, self.z1 = z0, z1
        self.v1_samples, self.v1_length = n, total
        self.runs = [(kept[r[0]] / self.m, kept[r[-1]] / self.m) for r in runs]
        self.crossings = []
        for f, i, j, u, v in far:
            self.crossings.append({"far_sample_t": kept[f] / self.m, **self._crossing(kept, i, j, u, v)})

    def _crossing(self, kept, i, j, u, v) -> dict:
        """交叉点的解析位置：以 v1 线段交点为初值，牛顿法解 S(t1) = S(t2)。"""
        t1 = (kept[i] + u * (kept[i + 1] - kept[i])) / self.m
        t2 = (kept[j] + v * (kept[j + 1] - kept[j])) / self.m
        for _ in range(30):
            (p1, d1, _, _, _), (p2, d2, _, _, _) = self.point(t1), self.point(t2)
            fx, fy = p1[0] - p2[0], p1[1] - p2[1]
            det = d1[0] * -d2[1] - (-d2[0]) * d1[1]
            s1 = (fx * -d2[1] - (-d2[0]) * fy) / det
            s2 = (d1[0] * fy - d1[1] * fx) / det
            t1, t2 = t1 - s1, t2 - s2
            if abs(s1) + abs(s2) < 1e-15:
                break
        (pt, _, _, za, _), (_, _, _, zb, _) = self.point(t1), self.point(t2)
        return {"t": [t1, t2], "point": list(pt), "depth": [za, zb], "far": 0 if za < zb else 1}

    # ---- 弧长与线宽 ---------------------------------------------------------------------------------

    def _speed(self, t: float) -> float:
        return math.hypot(*self.point(t)[1])

    def _gauss(self, a: float, b: float) -> float:
        h, c = (b - a) / 2, (a + b) / 2
        return h * sum(wt * self._speed(c + h * x) for x, wt in GAUSS)

    def _arc_table(self, n: int = 4000) -> None:
        self._h = self.t_end / n
        cum = [0.0]
        for i in range(n):
            cum.append(cum[-1] + self._gauss(i * self._h, (i + 1) * self._h))
        self._cum = cum
        self.length = cum[-1]

    def arc(self, t: float) -> float:
        """屏幕弧长 L(t)。"""
        i = min(len(self._cum) - 2, max(0, int(t / self._h)))
        return self._cum[i] + self._gauss(i * self._h, t)

    def arc_inverse(self, s: float) -> float:
        lo, hi = 0.0, self.t_end
        for _ in range(80):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if self.arc(mid) < s else (lo, mid)
        return (lo + hi) / 2

    def _raw_width(self, t: float):
        """未截底的线宽及其导数。"""
        _, d1, _, depth, d_depth = self.point(t)
        s, ds = self.arc(t), math.hypot(*d1)
        span = self.length * self.taper
        e, de = 1.0, 0.0
        if s / span < e:
            e, de = s / span, ds / span
        if (self.length - s) / span < e:
            e, de = (self.length - s) / span, -ds / span
        k = (self.w_near - self.w_far) / (self.z1 - self.z0)
        base, d_base = self.w_far + k * (depth - self.z0), k * d_depth
        g, dg = math.sin(e * math.pi / 2), math.cos(e * math.pi / 2) * math.pi / 2 * de
        return base * g, d_base * g + base * dg

    def width(self, t: float):
        w, dw = self._raw_width(t)
        return (self.w_floor, 0.0) if w <= self.w_floor else (w, dw)

    def _breaks(self) -> list[float]:
        """线宽导数不连续的位置：渐细段的两端与截底处。"""
        span = self.length * self.taper
        out = [self.arc_inverse(span), self.arc_inverse(self.length - span)]
        for lo, hi, rising in ((0.0, out[0], True), (out[1], self.t_end, False)):
            for _ in range(80):
                mid = (lo + hi) / 2
                below = self._raw_width(mid)[0] <= self.w_floor
                lo, hi = (mid, hi) if below == rising else (lo, mid)
            out.append((lo + hi) / 2)
        return sorted(out)

    # ---- 轮廓 ---------------------------------------------------------------------------------------

    def side(self, t: float, sign: int):
        """一侧轮廓（sign=+1 左、-1 右）上的点与对 t 的导数。"""
        s, d1, d2, _, _ = self.point(t)
        w, dw = self.width(t)
        sp = math.hypot(*d1)
        n = (-d1[1] / sp, d1[0] / sp)
        dot = d1[0] * d2[0] + d1[1] * d2[1]
        dn = (-d2[1] / sp + d1[1] * dot / sp**3, d2[0] / sp - d1[0] * dot / sp**3)
        h, dh = sign * w / 2, sign * dw / 2
        return (s[0] + n[0] * h, s[1] + n[1] * h), (d1[0] + dn[0] * h + n[0] * dh, d1[1] + dn[1] * h + n[1] * dh)

    def _fit(self, f, a: float, b: float, out: list, depth: int = 0) -> float:
        """在 [a, b] 上用 Hermite 三次贝塞尔逼近 f，误差超限时二分。返回最大误差。"""
        (p0, v0), (p3, v3) = f(a), f(b)
        k = (b - a) / 3
        p1, p2 = (p0[0] + v0[0] * k, p0[1] + v0[1] * k), (p3[0] - v3[0] * k, p3[1] - v3[1] * k)
        err = 0.0
        for i in range(1, 16):
            u = i / 16
            q = f(a + u * (b - a))[0]
            m = 1 - u
            bx = m**3 * p0[0] + 3 * m * m * u * p1[0] + 3 * m * u * u * p2[0] + u**3 * p3[0]
            by = m**3 * p0[1] + 3 * m * m * u * p1[1] + 3 * m * u * u * p2[1] + u**3 * p3[1]
            err = max(err, math.hypot(bx - q[0], by - q[1]))
        if err > self.tol and depth < 24:
            mid = (a + b) / 2
            return max(self._fit(f, a, mid, out, depth + 1), self._fit(f, mid, b, out, depth + 1))
        out.append((p0, p1, p2, p3))
        return err

    def _cap(self, t: float, forward: bool) -> list:
        """半圆圆头（两段四分之一圆弧）。forward：段尾从左绕到右；否则段首从右绕到左。"""
        c, d1, _, _, _ = self.point(t)
        r = self.width(t)[0] / 2
        sp = math.hypot(*d1)
        tx, ty = d1[0] / sp, d1[1] / sp
        nx, ny = -ty, tx
        if forward:
            dirs = [(nx, ny), (tx, ty), (-nx, -ny)]
        else:
            dirs = [(-nx, -ny), (-tx, -ty), (nx, ny)]
        segs = []
        for (ux, uy), (vx, vy) in pairwise(dirs):
            a = (c[0] + ux * r, c[1] + uy * r)
            b = (c[0] + vx * r, c[1] + vy * r)
            segs.append((a, (a[0] + vx * r * KAPPA, a[1] + vy * r * KAPPA), (b[0] + ux * r * KAPPA, b[1] + uy * r * KAPPA), b))
        return segs

    def outline(self) -> dict:
        """每段断开的线条一条闭合轮廓：左侧正向 → 段尾圆头 → 右侧反向 → 段首圆头。"""
        breaks = self._breaks()
        contours, worst = [], 0.0
        for a, b in self.runs:
            knots = [a] + [x for x in breaks if a < x < b] + [b]
            sides = {}
            for sign in (1, -1):
                segs = []
                for lo, hi in pairwise(knots):
                    pieces = max(1, math.ceil((hi - lo) / 0.05))
                    for i in range(pieces):
                        worst = max(worst, self._fit(lambda t, s=sign: self.side(t, s), lo + (hi - lo) * i / pieces,
                                                     lo + (hi - lo) * (i + 1) / pieces, segs))
                sides[sign] = segs
            right = [(q3, q2, q1, q0) for q0, q1, q2, q3 in reversed(sides[-1])]
            contours.append(sides[1] + self._cap(b, True) + right + self._cap(a, False))
        return {"contours": contours, "max_error": worst}

    def path(self) -> str:
        """整条标志的 SVG path（设计坐标，非零环绕填充）。"""
        f = lambda p: f"{num(p[0], self.digits)} {num(p[1], self.digits)}"  # noqa: E731
        parts = []
        for segs in self.outline()["contours"]:
            parts.append("M" + f(segs[0][0]) + "".join("C" + " ".join(f(q) for q in s[1:]) for s in segs) + "Z")
        return "".join(parts)

    # ---- 复核 ---------------------------------------------------------------------------------------

    def v1_deviation(self) -> float:
        """矢量轮廓与 v1 折线顶点（同一取样参数处）的最大距离，设计坐标。"""
        worst = 0.0
        for k, (left, right) in self._v1_edges.items():
            t = k / self.m
            for sign, old in ((1, left), (-1, right)):
                new = self.side(t, sign)[0]
                worst = max(worst, math.dist(new, old))
        return worst

    def icon_transform(self, tile: int, mark: float) -> tuple[float, float, float]:
        """标志放进边长 tile 的方块、外框长边占 mark 时的平移与缩放（按 v1 的取整：平移 0.1、缩放 0.0001）。"""
        x, y, w, h = self.box
        s = tile * mark / max(w, h)
        return round(tile / 2 - (x + w / 2) * s, 1), round(tile / 2 - (y + h / 2) * s, 1), round(s, 4)
