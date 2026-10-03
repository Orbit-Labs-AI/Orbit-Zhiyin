"""生成 Orbit 标志的全部矢量文件（SVG、PDF）与几何记录 orbit-geometry.json。

参数只有一处：orbit-spec.json；几何由 orbit.py 解析计算（锥形螺旋 → 投影 → 近粗远细的线宽与断口 →
三次贝塞尔轮廓）。所有文件共用同一条 path（设计坐标，边长 512），外层只套平移与等比缩放，
所以任何尺寸、任何底色的标志都是 App 图标那条曲线的等比缩放，线宽变化与断口比例完全一致。
位图（PNG、ICO、ICNS）由 export.mjs 从这里的 SVG 渲染。

用法（仓库根目录）：
  python3 docs/design/logo/generate.py           # 写出全部文件
  python3 docs/design/logo/generate.py --check   # 只比对：文件与参数不一致时列出并以 1 退出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from orbit import KAPPA, Orbit, load_spec, num

ROOT = Path(__file__).parent
KIT = ROOT / "kit"


def rgb(color: str) -> str:
    c = color.lstrip("#")
    return " ".join(num(int(c[i : i + 2], 16) / 255, 4) for i in (0, 2, 4))


def pdf(width: float, height: float, content: str) -> bytes:
    """单页 PDF（不压缩，字节稳定）。content 为页面内容流。"""
    body = content.encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {num(width)} {num(height)}] /Contents 4 0 R "
        "/Resources << >> >>".encode("ascii"),
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class Brand:
    """由同一条轮廓派生全部素材。"""

    def __init__(self, spec: dict):
        self.spec = spec
        self.orbit = Orbit(spec)
        out = self.orbit.outline()
        self.contours, self.fit_error = out["contours"], out["max_error"]
        self.digits = spec["vector"]["digits"]
        self.d = self.orbit.path()
        self.c = spec["colors"]
        tile = spec["tile"]
        self.tile, self.radius = tile["size"], tile["radius"]
        self.tx, self.ty, self.s = self.orbit.icon_transform(tile["size"], tile["mark"])
        self.icon_tr = f"translate({num(self.tx, 1)} {num(self.ty, 1)}) scale({num(self.s, 4)})"
        self.box = tuple(round(v, 1) for v in self.orbit.box)  # 紧凑画布（设计坐标，取 0.1，与 v1 相同）
        dock = spec["dock"]
        self.dock_canvas, self.dock_tile = dock["canvas"], dock["tile"]
        self.dock_k = dock["tile"] / tile["size"]
        self.dock_at = (dock["canvas"] - dock["tile"]) / 2
        self.shadow = dock["shadow"]

    # ---- SVG ----------------------------------------------------------------------------------------

    @staticmethod
    def _svg(view: str, w, h, body: str, head: str = "") -> str:
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{w}" height="{h}">{head}{body}</svg>\n'

    def _mark(self, fill: str, transform: str | None = None, cls: str = "") -> str:
        tr = f' transform="{transform}"' if transform else ""
        cl = f' class="{cls}"' if cls else ""
        return f'<g{cl} fill="{fill}"{tr}><path d="{self.d}"/></g>'

    def tight(self, fill: str) -> str:
        """透明底、紧凑画布（外框 + 4 留白），宽高比 = 标志本身。"""
        x, y, w, h = self.box
        return self._svg(f"{num(x, 1)} {num(y, 1)} {num(w, 1)} {num(h, 1)}", f"{w:.0f}", f"{h:.0f}", self._mark(fill))

    def square(self, fill: str) -> str:
        """透明底、1024 方形画布，标志位置与 App 图标完全相同（只去掉底板）。"""
        n = self.tile
        return self._svg(f"0 0 {n} {n}", n, n, self._mark(fill, self.icon_tr))

    def app_icon(self, bg: str, ink: str, rounded: bool = True) -> str:
        n = self.tile
        rx = f' rx="{self.radius}"' if rounded else ""
        return self._svg(f"0 0 {n} {n}", n, n, f'<rect width="{n}" height="{n}"{rx} fill="{bg}"/>' + self._mark(ink, self.icon_tr))

    def favicon(self) -> str:
        """App 图标；浏览器处于深色模式时换成黑夜版配色。"""
        n, c = self.tile, self.c
        style = f"<style>@media (prefers-color-scheme: dark){{.t{{fill:{c['night_tile']}}}.m{{fill:{c['night_ink']}}}}}</style>"
        body = f'<rect class="t" width="{n}" height="{n}" rx="{self.radius}" fill="{c["paper"]}"/>' + self._mark(c["ink"], self.icon_tr, "m")
        return self._svg(f"0 0 {n} {n}", n, n, body, style)

    def dock(self, bg: str, ink: str) -> str:
        """macOS Dock 网格：1024 画布中央 824 圆角方块（四周透明留白）+ 投影；方块内与 App 图标等比。"""
        n, at, k, sh = self.dock_canvas, self.dock_at, self.dock_k, self.shadow
        head = (f'<defs><filter id="shadow" x="-10%" y="-10%" width="120%" height="125%">'
                f'<feDropShadow dx="0" dy="{num(sh["dy"])}" stdDeviation="{num(sh["blur"])}" flood-color="#000000" '
                f'flood-opacity="{num(sh["opacity"])}"/></filter></defs>')
        rect = (f'<rect x="{num(at)}" y="{num(at)}" width="{self.dock_tile}" height="{self.dock_tile}" '
                f'rx="{num(self.radius * k)}" fill="{bg}" filter="url(#shadow)"/>')
        return self._svg(f"0 0 {n} {n}", n, n, rect + self._mark(ink, f"translate({num(at)} {num(at)}) scale({num(k, 7)}) {self.icon_tr}"), head)

    def social(self, bg: str, ink: str, w: int = 1280, h: int = 640) -> str:
        """分享图：边长 h 的 App 图标（去掉圆角）放在 w × h 的同色底上居中。"""
        k = h / self.tile
        tr = f"translate({num((w - h) / 2)} 0) scale({num(k, 7)}) {self.icon_tr}"
        return self._svg(f"0 0 {w} {h}", w, h, f'<rect width="{w}" height="{h}" fill="{bg}"/>' + self._mark(ink, tr))

    # ---- PDF ----------------------------------------------------------------------------------------

    def _pdf_path(self) -> str:
        f = lambda p: f"{num(p[0], self.digits)} {num(p[1], self.digits)}"  # noqa: E731
        out = []
        for segs in self.contours:
            out.append(f(segs[0][0]) + " m")
            out += [" ".join(f(q) for q in s[1:]) + " c" for s in segs]
            out.append("h")
        return "\n".join(out) + "\nf"

    @staticmethod
    def _pdf_rect(x: float, y: float, w: float, h: float, r: float) -> str:
        k = r * KAPPA
        pts = [
            f"{num(x + r)} {num(y)} m",
            f"{num(x + w - r)} {num(y)} l",
            f"{num(x + w - r + k)} {num(y)} {num(x + w)} {num(y + r - k)} {num(x + w)} {num(y + r)} c",
            f"{num(x + w)} {num(y + h - r)} l",
            f"{num(x + w)} {num(y + h - r + k)} {num(x + w - r + k)} {num(y + h)} {num(x + w - r)} {num(y + h)} c",
            f"{num(x + r)} {num(y + h)} l",
            f"{num(x + r - k)} {num(y + h)} {num(x)} {num(y + h - r + k)} {num(x)} {num(y + h - r)} c",
            f"{num(x)} {num(y + r)} l",
            f"{num(x)} {num(y + r - k)} {num(x + r - k)} {num(y)} {num(x + r)} {num(y)} c",
            "h",
            "f",
        ]
        return "\n".join(pts)

    def tight_pdf(self, fill: str) -> bytes:
        x, y, w, h = self.box
        body = f"q\n1 0 0 -1 {num(-x, 1)} {num(y + h, 1)} cm\n{rgb(fill)} rg\n{self._pdf_path()}\nQ\n"
        return pdf(w, h, body)

    def square_pdf(self, fill: str, bg: str | None = None) -> bytes:
        n = self.tile
        tile = f"{rgb(bg)} rg\n{self._pdf_rect(0, 0, n, n, self.radius)}\n" if bg else ""
        mark = f"q\n{num(self.s, 4)} 0 0 {num(self.s, 4)} {num(self.tx, 1)} {num(self.ty, 1)} cm\n{rgb(fill)} rg\n{self._pdf_path()}\nQ\n"
        return pdf(n, n, f"q\n1 0 0 -1 0 {n} cm\n{tile}{mark}Q\n")

    # ---- 文件清单 -----------------------------------------------------------------------------------

    def files(self) -> dict[Path, str | bytes]:
        c = self.c
        light, night = (c["paper"], c["ink"]), (c["night_tile"], c["night_ink"])
        marks = {"ink": c["ink"], "black": c["black"], "white": c["white"], "paper": c["paper"]}
        out: dict[Path, str | bytes] = {
            # 兼容文件名：README、原型 brand-icon.mjs、App 构建与 PPT 素材引用它们
            ROOT / "orbit-icon.svg": self.app_icon(*light),
            ROOT / "orbit-mark.svg": self.tight(c["ink"]),
            ROOT / "orbit-mark-light.svg": self.tight(c["paper"]),
            KIT / "app-icon/orbit-app-icon.svg": self.app_icon(*light),
            KIT / "app-icon/orbit-app-icon.pdf": self.square_pdf(c["ink"], c["paper"]),
            KIT / "app-icon/orbit-app-icon-night.svg": self.app_icon(*night),
            KIT / "app-icon/orbit-app-icon-night.pdf": self.square_pdf(c["night_ink"], c["night_tile"]),
            KIT / "dock/orbit-dock.svg": self.dock(*light),
            KIT / "dock/orbit-dock-night.svg": self.dock(*night),
            KIT / "favicon/favicon.svg": self.favicon(),
            KIT / "favicon/orbit-icon-square.svg": self.app_icon(*light, rounded=False),
            KIT / "social/orbit-social.svg": self.social(*light),
            KIT / "social/orbit-social-night.svg": self.social(*night),
        }
        for name, fill in marks.items():
            out[KIT / f"mark/orbit-mark-{name}.svg"] = self.tight(fill)
            out[KIT / f"mark/orbit-mark-{name}.pdf"] = self.tight_pdf(fill)
            if name != "paper":
                out[KIT / f"mark/orbit-mark-square-{name}.svg"] = self.square(fill)
                out[KIT / f"mark/orbit-mark-square-{name}.pdf"] = self.square_pdf(fill)
        out[ROOT / "orbit-geometry.json"] = self.geometry()
        return out

    def geometry(self) -> str:
        """解析常数、各素材的放置变换与 path，供复核与其他实现（Swift、Figma、前端）引用。"""
        o, r = self.orbit, lambda v: round(v, 9)
        x, y, w, h = self.box
        long_side = max(o.box[2], o.box[3])
        segs = sum(len(c) for c in self.contours)
        sw = self.spec["stroke"]
        doc = {
            "generator": "docs/design/logo/generate.py",
            "spec": "docs/design/logo/orbit-spec.json",
            "design_space": self.spec["design"]["size"],
            "projection": {"scale": r(o.scale), "center": [r(o.cx), r(o.cy)]},
            "v1": {
                "samples": o.v1_samples,
                "t_end": r(o.t_end),
                "depth_range": [r(o.z0), r(o.z1)],
                "polyline_length": r(o.v1_length),
                "runs": [[r(a), r(b)] for a, b in o.runs],
                "crossings": [
                    {"far_sample_t": r(c["far_sample_t"]), "t": [r(v) for v in c["t"]], "point": [r(v) for v in c["point"]],
                     "depth": [r(v) for v in c["depth"]], "far_branch": c["far"]}
                    for c in o.crossings
                ],
                "box": [r(v) for v in o.box],
            },
            "length": r(o.length),
            "ratios": {
                "note": "相对标志外框长边（含 4 单位留白）的比例；任何尺寸都应保持这些比例",
                "w_far": r(sw["w_far"] / long_side),
                "w_near": r(sw["w_near"] / long_side),
                "gap": r(sw["gap"] / long_side),
                "aspect": r(o.box[2] / o.box[3]),
            },
            "placements": {
                "tight": {"viewBox": f"{num(x, 1)} {num(y, 1)} {num(w, 1)} {num(h, 1)}"},
                "tile": {"canvas": self.tile, "radius": self.radius, "transform": self.icon_tr,
                         "stroke_px": {"w_far": r(sw["w_far"] * self.s), "w_near": r(sw["w_near"] * self.s), "gap": r(sw["gap"] * self.s)}},
                "dock": {"canvas": self.dock_canvas, "tile": [self.dock_at, self.dock_at, self.dock_tile, self.dock_tile],
                         "radius": r(self.radius * self.dock_k), "shadow": self.shadow,
                         "transform": f"translate({num(self.dock_at)} {num(self.dock_at)}) scale({num(self.dock_k, 7)}) {self.icon_tr}"},
            },
            "outline": {"contours": len(self.contours), "segments": segs, "fit_tolerance": self.spec["vector"]["tolerance"],
                        "fit_error": r(self.fit_error), "v1_deviation": r(o.v1_deviation()), "d": self.d},
        }
        return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def check_paths(files: dict[Path, str | bytes], d: str) -> list[str]:
    """每个 SVG 都必须且只能含这一条 path。"""
    errors = []
    for path, text in files.items():
        if path.suffix == ".svg":
            found = re.findall(r'<path d="([^"]*)"', text)
            if found != [d] or re.search(r"<(polygon|circle|polyline|line)\b", text):
                errors.append(f"{path.relative_to(ROOT)}: 标志不是母版 path")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只比对，不写文件")
    args = ap.parse_args()
    brand = Brand(load_spec())
    files = brand.files()
    errors = check_paths(files, brand.d)
    stale = []
    for path, data in files.items():
        raw = data.encode("utf-8") if isinstance(data, str) else data
        if args.check:
            if not path.exists() or path.read_bytes() != raw:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    if not args.check:
        print(f"{len(files)} files; {len(brand.contours)} contours, fit error {brand.fit_error:.4f}, "
              f"v1 deviation {brand.orbit.v1_deviation():.4f} (design units)")
    if stale:
        errors.append("与 orbit-spec.json 不一致（运行 python3 docs/design/logo/generate.py）：" + "、".join(stale))
    if errors:
        sys.exit("\n".join(errors))
    if args.check:
        print(f"logo: {len(files)} vector files match orbit-spec.json")


if __name__ == "__main__":
    main()
