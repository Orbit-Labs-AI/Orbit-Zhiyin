"""生成 Tandem 莫比乌斯环 logo（SVG，纯色线稿）。

莫比乌斯带的边缘只有一条闭合曲线。取参数式
    r = R + W·cos(u/2),  z = W·sin(u/2),  u ∈ [0, 4π)
即沿带子一侧边走两圈回到起点。把这条空间曲线倾斜投影后一笔画出：近处线粗、远处线细，
投影交叉处让较远的一支断开。只用一种颜色。

用法：python3 docs/design/logo/generate.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).parent

INK = "#5f6b6f"  # 低饱和板岩灰
PAPER = "#f5f4f0"

R = 1.0  # 中心圆半径
W = 0.48  # 半带宽
TILT = math.radians(-55)  # 俯仰
SPIN = math.radians(-110)  # 绕竖轴旋转，决定交叉点的位置
N = 1600  # 采样数

SIZE = 512  # 绘制坐标系边长
PAD = 4
GAP = 14  # 交叉处断开的留白


def space_curve():
    pts = []
    for k in range(N):
        u = 4 * math.pi * k / N
        r = R + W * math.cos(u / 2)
        x, y, z = r * math.cos(u), r * math.sin(u), W * math.sin(u / 2)
        x, y = x * math.cos(SPIN) - y * math.sin(SPIN), x * math.sin(SPIN) + y * math.cos(SPIN)
        y, z = y * math.cos(TILT) - z * math.sin(TILT), y * math.sin(TILT) + z * math.cos(TILT)
        pts.append((x, -y, z))  # SVG 的 y 轴向下；z 越大越近
    return pts


def far_crossings(p) -> list[int]:
    """投影后自交点处较远那一支的采样下标。"""
    n, out = len(p), []
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        for j in range(i + 2, n):
            if (j + 1) % n == i:
                continue
            c, d = p[j], p[(j + 1) % n]
            den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
            if abs(den) < 1e-12:
                continue
            t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den
            s = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / den
            if 0 <= t < 1 and 0 <= s < 1:
                za, zc = a[2] + t * (b[2] - a[2]), c[2] + s * (d[2] - c[2])
                out.append(i if za < zc else j)
    return out


def shapes(wmin: float, wmax: float) -> tuple[list[str], tuple[float, float, float, float]]:
    """返回填充图形与边界框。线宽按深度在 [wmin, wmax] 间变化；两者相等即等粗线。"""
    p = space_curve()
    n = len(p)
    xs, ys, zs = [q[0] for q in p], [q[1] for q in p], [q[2] for q in p]
    sc = (SIZE - 2 * 40) / max(max(xs) - min(xs), max(ys) - min(ys))
    P = [((x - min(xs)) * sc, (y - min(ys)) * sc) for x, y, _ in p]
    z0, z1 = min(zs), max(zs)
    w = [wmin + (wmax - wmin) * (z - z0) / (z1 - z0) for z in zs]

    length = [0.0]
    for i in range(n):
        length.append(length[-1] + math.dist(P[i], P[(i + 1) % n]))
    cut = set()
    for i in far_crossings(p):
        for j in range(n):
            dd = abs(length[j] - length[i])
            if min(dd, length[-1] - dd) < GAP / 2 + max(w[i], w[j]):
                cut.add(j)

    start = next(k for k in range(n) if k not in cut and (k - 1) % n in cut)
    runs, cur = [], []
    for m in range(n + 1):
        k = (start + m) % n
        if k in cut:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
        else:
            cur.append(k)
    if len(cur) > 1:
        runs.append(cur)

    out, edge = [], []
    for run in runs:
        left, right = [], []
        for k in run:
            (x0, y0), (x1, y1) = P[(k - 1) % n], P[(k + 1) % n]
            ln = math.hypot(x1 - x0, y1 - y0)
            nx, ny, h = -(y1 - y0) / ln, (x1 - x0) / ln, w[k] / 2
            left.append((P[k][0] + nx * h, P[k][1] + ny * h))
            right.append((P[k][0] - nx * h, P[k][1] - ny * h))
        edge += left + right
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in left + right[::-1])
        out.append(f'<polygon points="{poly}"/>')
        for k in (run[0], run[-1]):  # 圆头
            out.append(f'<circle cx="{P[k][0]:.1f}" cy="{P[k][1]:.1f}" r="{w[k] / 2:.2f}"/>')
    ex, ey = [x for x, _ in edge], [y for _, y in edge]
    box = (min(ex) - PAD, min(ey) - PAD, max(ex) - min(ex) + 2 * PAD, max(ey) - min(ey) + 2 * PAD)
    return out, box


def mark(color: str = INK, wmin: float = 4.5, wmax: float = 15) -> str:
    """紧凑画布、透明底。"""
    body, (x, y, w, h) = shapes(wmin, wmax)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}" '
        f'width="{w:.0f}" height="{h:.0f}"><g fill="{color}">{"".join(body)}</g></svg>\n'
    )


def icon(size: int = 1024) -> str:
    """方形图标：暖纸底圆角方块，标志居中。图标里线条偏粗，缩小后仍清楚。"""
    body, (x, y, w, h) = shapes(10, 24)
    s = size * 0.66 / max(w, h)
    tx, ty = size / 2 - (x + w / 2) * s, size / 2 - (y + h / 2) * s
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" rx="{size * 0.225:.0f}" fill="{PAPER}"/>'
        f'<g fill="{INK}" transform="translate({tx:.1f} {ty:.1f}) scale({s:.4f})">{"".join(body)}</g></svg>\n'
    )


def main():
    files = {
        "tandem-mark.svg": mark(),
        "tandem-mark-light.svg": mark(PAPER),
        "tandem-mark-small.svg": mark(wmin=34, wmax=34),
        "tandem-icon.svg": icon(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text)
        print(f"{name}: {len(text) // 1024} KB")


if __name__ == "__main__":
    main()
