"""
استخراج علامة «مثراة» من ريم كوفي كمسارات — اتجاه ٠٢ «النقاط تقيس».

    backend/.venv/bin/python scripts/build_wordmark.py

## بنية الخط

ريم كوفي يبني الكلمة من **هيكل بلا نقاط + رسوم نقاط مستقلّة** تُركَّب عليه
بمرساة. لذلك تُشكَّل «مثراة» إلى سبعة رسوم لا خمسة: خمسة هياكل، ونقاط الثاء
الثلاث، ونقطتا التاء المربوطة.

وهذا يعني أن الفصل الذي نحتاجه **موجود في الخط أصلاً**: لا تفكيك ولا تخمين.
نقاط الثاء رسمٌ قائم بذاته، نلوّنه وحده.

## كيف يُعرَف رسم النقاط

بعلامتين معاً، لا بالاسم (أسماء الرسوم تختلف بين إصدارات الخط):

  * `x_advance == 0` — أي أنه علامة تُركَّب ولا تشغل عرضاً.
  * عدد حدوده ثلاثة — فيفصله ذلك عن نقطتَي التاء المربوطة.

وإن لم يُوجد رسمٌ واحد بهاتين الصفتين، يتوقّف السكربت ولا يكتب شيئاً:
علامةٌ لُوِّن فيها الجزء الخطأ أسوأ من علامة غير مبنيّة.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FONT = REPO / "mobile" / "assets" / "fonts" / "ReemKufi.ttf"
OUT_DIR = REPO / "brand"

WORD = "مثراة"
WEIGHT = 600
DESIGN = 1000.0

INK = "#16161A"
EMBER = "#B85A26"


def die(msg: str) -> None:
    print(f"\033[31m⛔ {msg}\033[0m")
    sys.exit(1)


def contours_of(rec_value):
    """يقسم تسجيل القلم إلى حدود مستقلّة."""
    out, cur = [], []
    for op, args in rec_value:
        if op == "moveTo" and cur:
            out.append(cur)
            cur = []
        cur.append((op, args))
    if cur:
        out.append(cur)
    return out


def bbox_of(contour):
    xs, ys = [], []
    for _, args in contour:
        for pt in args:
            if isinstance(pt, tuple):
                xs.append(pt[0])
                ys.append(pt[1])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def main() -> None:
    try:
        import uharfbuzz as hb
        from fontTools.pens.recordingPen import RecordingPen
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        die(f"حزمة ناقصة: {exc}. نفّذي: backend/.venv/bin/pip install fonttools uharfbuzz")

    if not FONT.exists():
        die(f"الخط غير موجود: {FONT}")

    data = FONT.read_bytes()
    font = TTFont(FONT)
    upem = font["head"].unitsPerEm

    if "fvar" in font:
        from fontTools.varLib import instancer

        axes = {a.axisTag: (a.minValue, a.maxValue) for a in font["fvar"].axes}
        if "wght" not in axes:
            die(f"لا يوجد محور wght. المحاور: {list(axes)}")
        lo, hi = axes["wght"]
        w = min(max(WEIGHT, lo), hi)
        font = instancer.instantiateVariableFont(font, {"wght": w}, inplace=False)
        buf = io.BytesIO()
        font.save(buf)
        data = buf.getvalue()
        print(f"  ✅ ثُبّت الوزن على {w}")
    else:
        print("  ℹ️  الخط ثابت الوزن")

    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()

    face = hb.Face(data)
    hbfont = hb.Font(face)
    hbfont.scale = (upem, upem)
    hbuf = hb.Buffer()
    hbuf.add_str(WORD)
    hbuf.direction, hbuf.script, hbuf.language = "rtl", "Arab", "ar"
    hb.shape(hbfont, hbuf, {"kern": True, "liga": True})
    infos, positions = hbuf.glyph_infos, hbuf.glyph_positions
    print(f"  ✅ شُكِّلت «{WORD}» إلى {len(infos)} رسماً\n")

    # ---- تشخيص: ما الذي خرج فعلاً --------------------------------------
    print("  الرسوم كما خرجت من التشكيل:")
    print(f"  {'#':<3}{'الاسم':<26}{'تقدّم':>8}{'حدود':>7}   الارتفاع")
    print("  " + "─" * 62)
    rows = []
    for i, (info, pos) in enumerate(zip(infos, positions)):
        name = order[info.codepoint]
        rec = RecordingPen()
        glyphs[name].draw(rec)
        cs = contours_of(rec.value)
        bb = bbox_of([p for c in cs for p in c]) if cs else (0, 0, 0, 0)
        rows.append((i, name, pos.x_advance, cs, bb, pos))
        print(f"  {i:<3}{name:<26}{pos.x_advance:>8}{len(cs):>7}   {bb[1]:.0f}‥{bb[3]:.0f}")
    print()

    # ---- تعيين رسم نقاط الثاء ---------------------------------------------
    marks = [r for r in rows if r[2] == 0 and r[3]]
    three = [r for r in marks if len(r[3]) == 3]
    if len(three) != 1:
        die(
            f"لم أجد رسم نقاطٍ واحداً بثلاثة حدود وتقدّمٍ صفر. "
            f"العلامات ذات التقدّم الصفري: {[(r[1], len(r[3])) for r in marks]}. "
            "لم يُكتب شيء."
        )
    dots_index = three[0][0]
    print(f"  ✅ نقاط الثاء هي الرسم «{three[0][1]}» (الفهرس {dots_index})\n")

    # ---- بناء المسارات -----------------------------------------------------
    scale = DESIGN / upem
    body: list[str] = []
    dots: list[str] = []
    x = 0.0
    for i, name, adv, cs, bb, pos in rows:
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}")
        glyphs[name].draw(pen)
        d = pen.getCommands()
        if d:
            ox = (x + pos.x_offset) * scale
            oy = pos.y_offset * scale
            # y مقلوب: SVG ينمو لأسفل، وإحداثيات الخط تنمو لأعلى
            path = (
                f'<path transform="translate({ox:.1f},{-oy:.1f}) '
                f'scale({scale:.4f},{-scale:.4f})" d="{d}"/>'
            )
            (dots if i == dots_index else body).append(path)
        x += adv

    total_w = x * scale
    asc = font["hhea"].ascender * scale
    desc = font["hhea"].descender * scale
    pad = DESIGN * 0.10
    minx, miny = -pad, -asc - pad
    w, h = total_w + 2 * pad, (asc - desc) + 2 * pad

    def svg(dot_color: str) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{minx:.1f} {miny:.1f} {w:.1f} {h:.1f}" '
            f'width="{w:.0f}" height="{h:.0f}">'
            f'<g fill="{INK}">{"".join(body)}</g>'
            f'<g fill="{dot_color}">{"".join(dots)}</g></svg>'
        )

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "wordmark-ember.svg").write_text(svg(EMBER), encoding="utf-8")
    (OUT_DIR / "wordmark-mono.svg").write_text(svg(INK), encoding="utf-8")
    print(f"\033[32m✅ كُتبت في brand/\033[0m")
    print("   wordmark-ember.svg   ·   wordmark-mono.svg")


if __name__ == "__main__":
    main()
