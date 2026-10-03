"""字标「Orbit·知音」的中文字体对比页：把候选字体逐一排成完整字标，写出 kit/compare/orbit-zhiyin-fonts.html。

O 与 rbit 用现行参数（orbit-spec.json），只替换知音与中文间隔点的字体；排列规则与 wordmark.py 完全相同
（知音高 cjk.height × H、底边与基线对齐；点在基线上方 dot.height × H；间距 spacing）。字体缺「·」时借用现行字体的点。
每款给浅色底（板岩灰）与深色底（night_word）两版，并注明授权。字体下载缓存在 .work/font-cache/（已忽略）。

  uv run --no-project --with fonttools python docs/design/logo/compare_cjk.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import extract_glyphs
from generate import Brand
from orbit import load_spec, num
from wordmark import TEXT, Wordmark

ROOT = Path(__file__).parent
CACHE = ROOT.parents[2] / ".work" / "font-cache"
OUT = ROOT / "kit" / "compare" / "orbit-zhiyin-fonts.html"
GF = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
GH = "https://github.com/"

# (名称, 字体族, 字重, 来源, 授权)
CANDIDATES = [
    ("思源黑体 Light", "Noto Sans SC", 300, GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf", "OFL"),
    ("思源黑体 350", "Noto Sans SC", 350, GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf", "OFL"),
    ("思源黑体 Regular", "Noto Sans SC", 400, GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf", "OFL"),
    ("思源黑体 SemiBold（现行）", "Noto Sans SC", 600, GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf", "OFL"),
    ("思源宋体 Regular", "Noto Serif SC", 400, GF + "notoserifsc/NotoSerifSC%5Bwght%5D.ttf", "OFL"),
    ("思源宋体 SemiBold", "Noto Serif SC", 600, GF + "notoserifsc/NotoSerifSC%5Bwght%5D.ttf", "OFL"),
    ("霞鹜文楷", "LXGW WenKai TC", 400, GF + "lxgwwenkaitc/LXGWWenKaiTC-Regular.ttf", "OFL"),
    ("霞鹜新晰黑", "LXGW Neo XiHei", 400, GH + "lxgw/LxgwNeoXiHei/releases/download/v1.305/LXGWNeoXiHei.ttf", "IPA（非 OFL，商用前需确认）"),
    ("得意黑", "Smiley Sans", 400, GH + "atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip#SmileySans-Oblique.ttf", "OFL"),
    ("寒蝉圆黑", "ChillRoundM", 400, GH + "Warren2060/ChillRound/releases/download/v1.805/ChillRoundM_v1.805.zip#ChillRoundM_v1.805/ChillRoundM.ttf", "OFL"),
    ("站酷小薇", "ZCOOL XiaoWei", 400, GF + "zcoolxiaowei/ZCOOLXiaoWei-Regular.ttf", "OFL"),
    ("站酷快乐体", "ZCOOL KuaiLe", 400, GF + "zcoolkuaile/ZCOOLKuaiLe-Regular.ttf", "OFL"),
    ("站酷庆科黄油体", "ZCOOL QingKe HuangYou", 400, GF + "zcoolqingkehuangyou/ZCOOLQingKeHuangYou-Regular.ttf", "OFL"),
    ("马善政楷书", "Ma Shan Zheng", 400, GF + "mashanzheng/MaShanZheng-Regular.ttf", "OFL"),
    ("龙藏体", "Long Cang", 400, GF + "longcang/LongCang-Regular.ttf", "OFL"),
    ("志莽行书", "Zhi Mang Xing", 400, GF + "zhimangxing/ZhiMangXing-Regular.ttf", "OFL"),
]


def cached_fetch(source: str, _fetch=extract_glyphs.fetch) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / hashlib.sha256(source.encode()).hexdigest()[:16]
    if not f.exists():
        f.write_bytes(_fetch(source))
    return f.read_bytes()


def main() -> None:
    extract_glyphs.fetch = cached_fetch
    spec = load_spec()
    brand = Brand(spec)
    c = spec["colors"]
    pad = spec["design"]["box_pad"]
    bx = brand.o.box
    ink = (bx[0] + pad, bx[1] + pad, bx[0] + bx[2] - pad, bx[1] + bx[3] - pad)
    base = json.loads((ROOT / spec["wordmark"]["glyphs"]).read_text(encoding="utf-8"))
    cards = []
    for name, family, weight, source, lic in CANDIDATES:
        cjk = extract_glyphs.extract({"family": family, "weight": weight, "source": source}, "知音·")
        note = ""
        if "·" not in cjk["glyphs"]:  # 借用现行字体的点，按字体单位比例换算
            k = cjk["units_per_em"] / base["cjk"]["units_per_em"]
            d = base["cjk"]["glyphs"]["·"]
            cjk["glyphs"]["·"] = {"advance": d["advance"] * k, "bounds": [v * k for v in d["bounds"]],
                                  "contours": [[[[q[0] * k, q[1] * k] for q in seg] for seg in ct] for ct in d["contours"]]}
            note = "；点借用思源黑体"
        wm = Wordmark(spec, ink, {"latin": base["latin"], "cjk": cjk})
        x0, y0, x1, y1 = wm.box
        vb = f"{num(x0 - pad, 1)} {num(y0 - pad, 1)} {num(x1 - x0 + 2 * pad, 1)} {num(y1 - y0 + 2 * pad, 1)}"
        body = f'<path d="{brand.o_d}"/><path d="{wm.path(2, TEXT)}"/>'
        cards.append(
            f'<article><h2>{name}</h2><p>{family} · {weight} · {lic}{note}</p>'
            f'<div class="l"><svg viewBox="{vb}"><g fill="{c["ink"]}">{body}</g></svg></div>'
            f'<div class="d"><svg viewBox="{vb}"><g fill="{c["night_word"]}">{body}</g></svg></div></article>'
        )
        print(f"{name}: ok{note}")
    css = (f"body{{margin:0;background:{c['paper']};color:#3b4245;font:14px -apple-system,'PingFang SC',sans-serif}}"
           "header{padding:32px 5vw 12px}h1{margin:0;font-size:24px}header p{color:#6b7376;max-width:900px}"
           "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:12px 5vw 40px}"
           "article{background:#fff;border:1px solid #e3e1dc;border-radius:12px;overflow:hidden}"
           "h2{font-size:15px;margin:14px 16px 0}article p{margin:2px 16px 10px;color:#6b7376;font-size:12px}"
           f".l,.d{{padding:18px 20px}}.l{{background:{c['paper']}}}.d{{background:{c['night_tile']}}}"
           "svg{display:block;width:100%;height:auto}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Orbit·知音 中文字体对比</title><style>{css}</style></head><body><header><h1>Orbit·知音 · 中文字体对比</h1>"
        f"<p>O 与 rbit（Josefin Sans {base['latin']['weight']}）不变，只替换「知音」与中文间隔点「·」的字体。知音高 {spec['wordmark']['cjk']['height']} H、"
        f"底边与 rbit 基线对齐；点在基线上方 {spec['wordmark']['dot']['height']} H，左右空隙 {spec['wordmark']['spacing']['t_dot']} H。"
        "上为浅色底，下为深色底（香槟黄）。由 docs/design/logo/compare_cjk.py 生成。</p></header>"
        f"<main>{''.join(cards)}</main></body></html>\n",
        encoding="utf-8",
    )
    print(f"{OUT.relative_to(ROOT)}: {len(CANDIDATES)} fonts, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
