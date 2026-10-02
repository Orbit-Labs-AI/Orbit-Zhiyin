"""生成 Tandem logo（SVG，纯色线稿）：洛伦茨吸引子的一段轨道。

由莫比乌斯带线稿演化而来，保留它的线条语言：一笔画、近粗远细、投影交叉处较远的一支断开。
线条换成洛伦茨吸引子（σ=10, ρ=28, β=8/3）的一段轨道：左右两翼各绕两圈，
两端渐细收笔。吸引子的拓扑模板本身是一条带扭转的分支带，与莫比乌斯带同源。
纯 Python 实现，不依赖第三方库；积分步长与初值固定，结果可复现。

用法：python3 docs/design/logo/generate.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).parent

INK = "#5f6b6f"  # 低饱和板岩灰
PAPER = "#f5f4f0"

# 轨道
SIGMA, RHO, BETA = 10.0, 28.0, 8 / 3
DT = 0.003
SKIP = 4000  # 丢弃的暂态步数
STEPS = 12000
FIRST_LOOP = 26  # 从第几圈开始（以 z 的局部极大值计圈）
LOOPS = 3  # 取几圈
HEAD, TAIL = -0.15, 0.2  # 起止点相对圈首的偏移（单位：一圈）

# 视角
YAW = math.radians(-30)  # 绕 z 轴
PITCH = math.radians(20)  # 绕 x 轴

# 线条（绘制坐标系边长 SIZE）
SIZE = 512
PAD = 48
W_MIN, W_MAX = 2.6, 11.0  # 远处 / 近处线宽
GAP = 20  # 交叉处断开的留白（沿线长度；交叉角小，需留宽一些）
TAPER = 0.10  # 两端渐细段占全长的比例


def lorenz() -> list[tuple[float, float, float]]:
    def f(x, y, z):
        return SIGMA * (y - x), x * (RHO - z) - y, x * y - BETA * z

    x, y, z = 1.0, 1.0, 1.0
    out = []
    for k in range(SKIP + STEPS):
        k1 = f(x, y, z)
        k2 = f(x + DT / 2 * k1[0], y + DT / 2 * k1[1], z + DT / 2 * k1[2])
        k3 = f(x + DT / 2 * k2[0], y + DT / 2 * k2[1], z + DT / 2 * k2[2])
        k4 = f(x + DT * k3[0], y + DT * k3[1], z + DT * k3[2])
        x += DT / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        y += DT / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
        z += DT / 6 * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2])
        if k >= SKIP:
            out.append((x, y, z - 25))
    return out


def segment() -> list[tuple[float, float, float]]:
    full = lorenz()
    peaks = [i for i in range(1, len(full) - 1) if full[i - 1][2] < full[i][2] >= full[i + 1][2]]
    a, b = FIRST_LOOP, FIRST_LOOP + LOOPS
    i0 = peaks[a] + int(HEAD * (peaks[a + 1] - peaks[a]))
    i1 = peaks[b] + int(TAIL * (peaks[b + 1] - peaks[b]))
    return full[i0:i1]


def project(pts):
    """正交投影：返回 (屏幕 x, 屏幕 y, 深度)，深度越大越近；按屏幕弧长重采样。"""
    out = []
    for x, y, z in pts:
        x1, y1 = x * math.cos(YAW) - y * math.sin(YAW), x * math.sin(YAW) + y * math.cos(YAW)
        y2, z2 = y1 * math.cos(PITCH) - z * math.sin(PITCH), y1 * math.sin(PITCH) + z * math.cos(PITCH)
        out.append((x1, -z2, -y2))
    xs, ys = [p[0] for p in out], [p[1] for p in out]
    sc = (SIZE - 2 * PAD) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    scaled = [(SIZE / 2 + (x - cx) * sc, SIZE / 2 + (y - cy) * sc, z) for x, y, z in out]
    res, acc = [scaled[0]], 0.0
    for i in range(1, len(scaled)):
        acc += math.dist(scaled[i][:2], scaled[i - 1][:2])
        if acc >= 1.5:
            res.append(scaled[i])
            acc = 0.0
    return res


def far_crossings(p) -> list[int]:
    """投影自交点处较远那一支的下标（网格加速）。"""
    cell, grid = 6.0, {}
    for i in range(len(p) - 1):
        a, b = p[i], p[i + 1]
        for gx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
            for gy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    seen, out = set(), []
    for items in grid.values():
        for m in range(len(items)):
            for n in range(m + 1, len(items)):
                i, j = sorted((items[m], items[n]))
                if j - i < 3 or (i, j) in seen:
                    continue
                seen.add((i, j))
                a, b, c, d = p[i], p[i + 1], p[j], p[j + 1]
                den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
                if abs(den) < 1e-12:
                    continue
                t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den
                s = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / den
                if 0 <= t < 1 and 0 <= s < 1:
                    za, zc = a[2] + t * (b[2] - a[2]), c[2] + s * (d[2] - c[2])
                    out.append(i if za < zc else j)
    return out


def shapes(w_min: float, w_max: float, gap: float):
    """返回填充图形与边界框。"""
    p = project(segment())
    n = len(p)
    length = [0.0]
    for i in range(1, n):
        length.append(length[-1] + math.dist(p[i][:2], p[i - 1][:2]))
    total = length[-1]
    z0, z1 = min(q[2] for q in p), max(q[2] for q in p)

    def width(k):
        e = min(1.0, length[k] / (total * TAPER), (total - length[k]) / (total * TAPER))
        return max(0.6, (w_min + (w_max - w_min) * (p[k][2] - z0) / (z1 - z0)) * math.sin(e * math.pi / 2))

    w = [width(k) for k in range(n)]
    cut = [False] * n
    for i in far_crossings(p):
        r = gap / 2 + w[i]
        for k in range(n):
            if abs(length[k] - length[i]) < r:
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

    out, edge = [], []
    for run in runs:
        left, right = [], []
        for k in run:
            a, b = p[max(0, k - 1)], p[min(n - 1, k + 1)]
            ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            nx, ny, h = -(b[1] - a[1]) / ln, (b[0] - a[0]) / ln, w[k] / 2
            left.append((p[k][0] + nx * h, p[k][1] + ny * h))
            right.append((p[k][0] - nx * h, p[k][1] - ny * h))
        edge += left + right
        out.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in left + right[::-1])}"/>')
        for k in (run[0], run[-1]):  # 圆头
            out.append(f'<circle cx="{p[k][0]:.1f}" cy="{p[k][1]:.1f}" r="{w[k] / 2:.2f}"/>')
    xs, ys = [x for x, _ in edge], [y for _, y in edge]
    return out, (min(xs) - 4, min(ys) - 4, max(xs) - min(xs) + 8, max(ys) - min(ys) + 8)


def mark(color: str = INK, w_min: float = W_MIN, w_max: float = W_MAX, gap: float = GAP) -> str:
    """紧凑画布、透明底。"""
    body, (x, y, w, h) = shapes(w_min, w_max, gap)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}" '
        f'width="{w:.0f}" height="{h:.0f}"><g fill="{color}">{"".join(body)}</g></svg>\n'
    )


def icon(size: int = 1024) -> str:
    """方形图标：暖纸底圆角方块，标志居中，线条加粗。"""
    body, (x, y, w, h) = shapes(4, 14, 24)
    s = size * 0.68 / max(w, h)
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
        # 小尺寸版：线宽拉平加粗，远处细线在 48 px 以下不会消失
        "tandem-mark-small.svg": mark(w_min=12, w_max=16, gap=30),
        "tandem-icon.svg": icon(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text)
        print(f"{name}: {len(text) // 1024} KB")


if __name__ == "__main__":
    main()
