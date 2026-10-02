"""生成 Tandem 莫比乌斯环 logo（SVG，纯色线稿）。

用三条沿带子走向的线表现莫比乌斯带：两条边缘线粗，中线细。线条按三种规则断开：
1. 遮挡：被带子其他部分挡住的地方断开，并在遮挡边缘留白（深度缓冲判断）；
2. 侧视：带面接近侧对观察者（扭转处）时，内部线条隐去，只留边缘；
3. 节奏：内部线条按各自的周期和相位留出间隙，避免一体成型。
只用一种颜色。纯 Python 实现，不依赖第三方库。

用法：python3 docs/design/logo/generate.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).parent

INK = "#94705f"  # 低饱和陶土色
PAPER = "#f5f4f0"

R = 1.0  # 中心圆半径
W = 0.55  # 半带宽
TILT = math.radians(45)  # 俯仰
SPIN = math.radians(-30)  # 绕竖轴旋转，决定扭转的位置
LINES = 3  # 横跨带宽的线条数（含两条边缘，取奇数）

SIZE = 512  # 绘制坐标系边长
EDGE_W = 7.0  # 边缘线宽
INNER_W = 3.4  # 内部线宽
OCCLUDE_GAP = 3  # 遮挡边缘的留白半径（px）
DEPTH_EPS = 0.12  # 深度比较容差
FACE_MIN = 0.3  # 带面朝向低于此值（接近侧视）时隐去内部线条
MIN_LEN = 14  # 短于此长度的碎线丢弃（px）
RES = 720  # 深度缓冲分辨率


def rhythm(j: int) -> tuple[float, float, float]:
    """第 j 条内部线的节奏中断：(周期, 实线占比, 相位)，单位 px。"""
    return 260 + j * 60, 0.86, 40 + j * 70


def point(u: float, v: float) -> tuple[float, float, float]:
    r = R + v * math.cos(u / 2)
    x, y, z = r * math.cos(u), r * math.sin(u), v * math.sin(u / 2)
    x, y = x * math.cos(SPIN) - y * math.sin(SPIN), x * math.sin(SPIN) + y * math.cos(SPIN)
    y, z = y * math.cos(TILT) - z * math.sin(TILT), y * math.sin(TILT) + z * math.cos(TILT)
    return x, -y, z  # SVG 的 y 轴向下；z 越大越近


def facing(u: float, v: float) -> float:
    """带面法向与视线夹角的 |cos|：1 为正对，0 为侧视。"""
    a, b = point(u - 1e-3, v), point(u + 1e-3, v)
    c = point(u, v - 1e-3 if v > 0 else v + 1e-3)
    t1 = [b[i] - a[i] for i in range(3)]
    t2 = [c[i] - a[i] for i in range(3)]
    n = (t1[1] * t2[2] - t1[2] * t2[1], t1[2] * t2[0] - t1[0] * t2[2], t1[0] * t2[1] - t1[1] * t2[0])
    return abs(n[2]) / math.sqrt(sum(q * q for q in n))


class Scene:
    def __init__(self, pad: float = 36):
        nu, nv = 360, 10
        grid = [[point(2 * math.pi * i / nu, -W + 2 * W * j / nv) for j in range(nv + 1)] for i in range(nu + 1)]
        xs = [p[0] for row in grid for p in row]
        ys = [p[1] for row in grid for p in row]
        self.sc = (SIZE - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
        self.ox = (SIZE - (max(xs) - min(xs)) * self.sc) / 2 - min(xs) * self.sc
        self.oy = (SIZE - (max(ys) - min(ys)) * self.sc) / 2 - min(ys) * self.sc
        self.zb = [[-1e9] * RES for _ in range(RES)]
        for i in range(nu):
            for j in range(nv):
                a, b, c, d = (self.screen(q) for q in (grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                self.raster(a, b, c)
                self.raster(a, c, d)

    def screen(self, p):
        return p[0] * self.sc + self.ox, p[1] * self.sc + self.oy, p[2]

    def raster(self, a, b, c):
        k = RES / SIZE
        A, B, C = [(p[0] * k, p[1] * k, p[2]) for p in (a, b, c)]
        den = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
        if abs(den) < 1e-9:
            return
        x0, x1 = max(0, int(min(A[0], B[0], C[0]))), min(RES - 1, int(max(A[0], B[0], C[0])) + 1)
        y0, y1 = max(0, int(min(A[1], B[1], C[1]))), min(RES - 1, int(max(A[1], B[1], C[1])) + 1)
        for y in range(y0, y1 + 1):
            row = self.zb[y]
            for x in range(x0, x1 + 1):
                l1 = ((B[1] - C[1]) * (x - C[0]) + (C[0] - B[0]) * (y - C[1])) / den
                l2 = ((C[1] - A[1]) * (x - C[0]) + (A[0] - C[0]) * (y - C[1])) / den
                l3 = 1 - l1 - l2
                if min(l1, l2, l3) >= -0.02:
                    z = l1 * A[2] + l2 * B[2] + l3 * C[2]
                    if z > row[x]:
                        row[x] = z

    def visible(self, x: float, y: float, z: float) -> bool:
        k, best = RES / SIZE, -1e9
        offsets = [(0.0, 0.0)] + [
            (OCCLUDE_GAP * math.cos(a), OCCLUDE_GAP * math.sin(a)) for a in (i * math.pi / 4 for i in range(8))
        ]
        for dx, dy in offsets:
            X, Y = int((x + dx) * k), int((y + dy) * k)
            if 0 <= X < RES and 0 <= Y < RES:
                best = max(best, self.zb[Y][X])
        return z >= best - DEPTH_EPS

    def strokes(self) -> list[tuple[bool, list[tuple[float, float]]]]:
        """返回 (是否边缘, 点列)。v 与 -v 在 u=2π 处首尾相接，所以只取 v ≥ 0，非中线走 4π。"""
        out = []
        for j in range(LINES // 2, LINES):
            v = -W + 2 * W * j / (LINES - 1)
            edge = j == LINES - 1
            span, n = (4 * math.pi, 1400) if v > 1e-9 else (2 * math.pi, 700)
            runs, cur, length, prev = [], [], 0.0, None
            for m in range(n + 1):
                u = span * m / n
                x, y, z = self.screen(point(u, v))
                if prev:
                    length += math.dist(prev, (x, y))
                prev = (x, y)
                on = self.visible(x, y, z)
                if not edge:
                    period, duty, phase = rhythm(j)
                    on = on and facing(u, v) >= FACE_MIN and (length + phase) % period < period * duty
                if on:
                    cur.append((x, y))
                elif cur:
                    runs.append(cur)
                    cur = []
            runs.append(cur)
            for r in runs:
                if len(r) > 1 and sum(math.dist(r[q], r[q + 1]) for q in range(len(r) - 1)) >= MIN_LEN:
                    out.append((edge, r))
        return out


def d(points) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points)


def paths(strokes, edge_w: float, inner_w: float) -> str:
    return "".join(f'<path d="{d(r)}" stroke-width="{edge_w if e else inner_w}"/>' for e, r in strokes)


def bbox(strokes, pad: float):
    xs = [x for _, r in strokes for x, _ in r]
    ys = [y for _, r in strokes for _, y in r]
    return min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad


LINE = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'


def mark(strokes, color: str = INK, edge_w: float = EDGE_W, inner_w: float = INNER_W) -> str:
    """紧凑画布、透明底。"""
    x, y, w, h = bbox(strokes, edge_w / 2 + 2)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}" '
        f'width="{w:.0f}" height="{h:.0f}"><g stroke="{color}" {LINE}>{paths(strokes, edge_w, inner_w)}</g></svg>\n'
    )


def icon(strokes, size: int = 1024) -> str:
    """方形图标：暖纸底圆角方块，标志居中，线条加粗。"""
    x, y, w, h = bbox(strokes, 0)
    s = size * 0.68 / max(w, h)
    tx, ty = size / 2 - (x + w / 2) * s, size / 2 - (y + h / 2) * s
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" rx="{size * 0.225:.0f}" fill="{PAPER}"/>'
        f'<g stroke="{INK}" {LINE} transform="translate({tx:.1f} {ty:.1f}) scale({s:.4f})">'
        f"{paths(strokes, EDGE_W * 1.3, INNER_W * 1.4)}</g></svg>\n"
    )


def main():
    strokes = Scene().strokes()
    files = {
        "tandem-mark.svg": mark(strokes),
        "tandem-mark-light.svg": mark(strokes, PAPER),
        "tandem-icon.svg": icon(strokes),
    }
    # 小尺寸版：内部细线在 48 px 以下会糊成杂点，只留加粗的边缘线
    files["tandem-mark-small.svg"] = mark([s for s in strokes if s[0]], edge_w=16)
    for name, text in files.items():
        (OUT / name).write_text(text)
        print(f"{name}: {len(text) // 1024} KB")


if __name__ == "__main__":
    main()
