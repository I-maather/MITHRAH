#!/usr/bin/env python3
"""
توليد أيقونة التطبيق والشاشة الافتتاحية — **أصل لا نائب**.

## لماذا لا تكفي الصور النائبة

App Store Review يرفض الأيقونات النائبة صراحةً. والأهم أن الأيقونة هي أول ما
يُرى، وأيقونة مؤقتة تبقى مؤقتة حتى لحظة الرفض.

## التصميم

حرف **م** (مآثر) مبنيّ هندسياً داخل قوس صاعد. لا رسم بياني كاذب ولا سهم
أخضر — النظام لا يَعِد بربح، فالأيقونة لا تُوحي به. القوس **محايد الاتجاه**:
يقرأه العين صعوداً أو هبوطاً بحسب موضعه، وهذا مقصود.

اللون من نظام التصميم نفسه في `src/theme/` — لا لون جديد يُخترع هنا.

**لا تقليد لعلامة Capital.com**: لا أزرق مؤسسي، ولا شكل مشتق، ولا خط مشابه.

    python3 scripts/generate-app-icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

#: من `src/theme/colors.ts` — الخلفية الداكنة نفسها.
INK = (13, 15, 17)
#: نحاسي هادئ: قيمة وثقل بلا صخب «المال الأخضر».
BRASS = (198, 160, 92)
BRASS_DIM = (142, 114, 66)
CANVAS = (247, 245, 242)


def _supersample(size: int, factor: int = 4) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    """يُرسَم بأربعة أضعاف الحجم ثم يُصغَّر — الحواف المائلة تحتاج ذلك."""
    big = size * factor
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), big


def draw_mark(draw: ImageDraw.ImageDraw, box: int, *, stroke: tuple[int, int, int],
              accent: tuple[int, int, int]) -> None:
    """
    العلامة: قوس مفتوح + ساقان + نقطة.

    النسب مشتقة من `box` كي تصحّ في كل مقاس، ولا تُكتب أرقام مطلقة تنكسر عند
    التصغير إلى 48 بكسل.
    """
    unit = box / 100.0
    width = int(7.5 * unit)

    # القوس — 200° مفتوح للأسفل، محايد الاتجاه عمداً.
    pad = 24 * unit
    draw.arc(
        [pad, pad, box - pad, box - pad],
        start=200, end=340, fill=stroke, width=width,
    )

    # الساقان: عمودان ينزلان من طرفي القوس.
    cx = cy = box / 2
    radius = (box - 2 * pad) / 2
    for angle in (200, 340):
        rad = math.radians(angle)
        x = cx + radius * math.cos(rad)
        y = cy + radius * math.sin(rad)
        draw.line([x, y, x, box - pad * 0.85], fill=stroke, width=width)

    # النقطة: مركز الثقل. أصغر من أن تُقرأ شعاراً مالياً.
    dot = 6.5 * unit
    draw.ellipse([cx - dot, cy - dot + 4 * unit, cx + dot, cy + dot + 4 * unit],
                 fill=accent)


def make_icon(size: int, *, background: tuple[int, int, int],
              stroke: tuple[int, int, int], accent: tuple[int, int, int],
              transparent: bool = False) -> Image.Image:
    image, draw, box = _supersample(size)
    if not transparent:
        draw.rectangle([0, 0, box, box], fill=background)
    draw_mark(draw, box, stroke=stroke, accent=accent)
    return image.resize((size, size), Image.LANCZOS)


def make_splash(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), INK)
    mark = make_icon(min(width, height) // 3, background=INK,
                     stroke=BRASS, accent=CANVAS, transparent=True)
    image.paste(mark, ((width - mark.width) // 2, (height - mark.height) // 2), mark)
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    outputs = {
        # أيقونة المتجر: **بلا شفافية وبلا زوايا مستديرة** — iOS يقصّها بنفسه،
        # وتقديمها مقصوصة سلفاً يُنتج حوافّ مزدوجة.
        "icon.png": make_icon(1024, background=INK, stroke=BRASS, accent=CANVAS),
        "adaptive-icon.png": make_icon(1024, background=INK, stroke=BRASS,
                                       accent=CANVAS, transparent=True),
        "favicon.png": make_icon(48, background=INK, stroke=BRASS, accent=CANVAS),
        "notification-icon.png": make_icon(96, background=INK, stroke=BRASS_DIM,
                                           accent=CANVAS, transparent=True),
    }
    # أيقونة المتجر **بلا قناة شفافية**: App Store Connect يرفض أي أيقونة
    # تحمل ألفا، حتى لو كانت معتمة بالكامل. البقية تحتفظ بالشفافية لأنها
    # تُركَّب فوق خلفيات مختلفة.
    opaque = {"icon.png", "favicon.png"}
    for name, image in outputs.items():
        path = ASSETS / name
        if name in opaque:
            flat = Image.new("RGB", image.size, INK)
            flat.paste(image, mask=image.split()[3])
            flat.save(path, "PNG")
            print(f"  ✅ {name}  {flat.width}×{flat.height}  RGB (بلا ألفا)")
        else:
            image.save(path, "PNG")
            print(f"  ✅ {name}  {image.width}×{image.height}  RGBA")

    splash = make_splash(1284, 2778)
    splash.save(ASSETS / "splash.png", "PNG")
    print(f"  ✅ splash.png  {splash.width}×{splash.height}")


if __name__ == "__main__":
    main()
