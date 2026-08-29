#!/usr/bin/env python3
"""
أيقونة مآثر — **الإسطرلاب**، بألوان جريئة.

## الإيجاز

الفكرة: أداة قياس عربية. دوائر متداخلة، وتدريج، ومؤشّر دقيق.
الإحساس: جريء وملوّن — تباين قوي وشخصية واضحة، لا تدرّج غروب مبتذل.

## لماذا الإسطرلاب مناسب لهذا النظام تحديداً

الإسطرلاب لا يتنبّأ. **يقيس ويحدّد موقعك**، وتفاؤله مصدره المعرفة لا الوعد.
وهذا وصف حرفيّ لما يفعله هذا التطبيق: لا يَعِد بربح، يقيس الظروف ويقول أين
أنت — وأغلب الأيام يقول `NO_TRADE`.

وبصرياً: الدوائر المتداخلة **ساكنة ومتيقّظة** في آن. لا سهم صاعد يكذب، ولا
رسم بياني يوحي بحركة ليست هناك.

## قواعد الرسم

  * ثلاث حلقات بأوزان مختلفة — التنويع يصنع إيقاعاً، والتساوي يصنع مللاً
  * تدريج شعاعي **قصير وسميك**، فالتفاصيل الرفيعة تختفي في 60 بكسل
  * مؤشّر (عضادة) قطريّ — القطر يمنع الجمود الذي يصنعه التناظر الكامل
  * التكوين **يخرج قليلاً عن الإطار**: الشكل المحصور في المنتصف بهوامش
    متساوية يبدو حذراً، والخارج عن الحد يبدو واثقاً

    python3 scripts/icon_astrolabe.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
OUT = ASSETS / "concepts"
FONT = ASSETS / "fonts" / "NotoKufiArabic-Bold.ttf"
SS = 4


# ---------------------------------------------------------------------------
# لوحات جريئة — تباين عالٍ وألوان مشبعة، ولا واحدة منها «أخضر الأرباح»
# ---------------------------------------------------------------------------

PALETTES = {
    "saffron": {
        "name_ar": "زعفران وليل",
        "field": (27, 27, 58),          # نيلي عميق
        "ring": (255, 183, 3),          # زعفران
        "accent": (251, 86, 7),         # مرجاني حارّ
        "mark": (255, 250, 240),
        "tick": (255, 183, 3),
    },
    "jewel": {
        "name_ar": "جوهرة",
        "field": (2, 48, 71),           # تركوازي داكن
        "ring": (0, 180, 216),          # سماوي حيّ
        "accent": (255, 0, 110),        # أرجواني صارخ
        "mark": (241, 250, 255),
        "tick": (0, 180, 216),
    },
    "electric": {
        "name_ar": "كهربائي",
        "field": (58, 12, 163),         # بنفسجي عميق
        "ring": (76, 201, 240),         # سماوي فاتح
        "accent": (247, 37, 133),       # وردي كهربائي
        "mark": (255, 255, 255),
        "tick": (76, 201, 240),
    },
    "solar": {
        "name_ar": "شمسي",
        "field": (255, 123, 0),         # برتقالي مشبع
        "ring": (48, 16, 60),           # حبر بنفسجي
        "accent": (0, 187, 249),        # سماوي مقابل
        "mark": (32, 12, 40),
        "tick": (48, 16, 60),
    },
    "pomegranate": {
        "name_ar": "رمّان",
        "field": (155, 18, 45),         # رمّاني عميق
        "ring": (255, 199, 95),         # ذهب فاتح
        "accent": (0, 168, 150),        # زمرّدي مقابل
        "mark": (255, 245, 235),
        "tick": (255, 199, 95),
    },
}


def _rgba(colour, alpha: int = 255):
    return (*colour, alpha)


def draw_astrolabe(base: Image.Image, palette: dict, *, box: int,
                   with_meem: bool = True,
                   needle_style: str = "inner") -> Image.Image:
    """
    الأداة بأقلّ عدد ممكن من العناصر: تدريج + حلقة واحدة + مؤشّر + مركز.

    ## ما حُذف في المراجعة الثانية، ولماذا

    * **حلقة من اثنتين** — الحلقتان تتنافسان، ولا تُقرأ أيٌّ منهما في 60 بكسل.
    * **12 علامة بدل 24** — نصف العدد بضعف السُّمك يعطي إيقاعاً أوضح وأقوى.
    * **مؤشّر واحد بدل عضادة عابرة** — العضادة بطرفين مستديرين كانت تُقرأ
      **لصقة جروح**. الإبرة من المركز إلى الحافة أوضح دلالةً وأنظف شكلاً.
    * **حرف أكبر** — كان يضيع بين الزخارف.

    التصميم انضباط طرح. كل عنصر بقي هنا دفع ثمن بقائه.
    """
    layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = cy = box / 2
    u = box / 100.0

    ring = palette["ring"]
    accent = palette["accent"]

    # --- التدريج: اثنتا عشرة علامة سميكة، أربعٌ منها أطول ---
    outer_r = 45 * u
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        major = i % 3 == 0
        length = (11 if major else 6.5) * u
        width = int((6.5 if major else 5.0) * u)
        x1 = cx + (outer_r - length) * math.cos(angle)
        y1 = cy + (outer_r - length) * math.sin(angle)
        x2 = cx + outer_r * math.cos(angle)
        y2 = cy + outer_r * math.sin(angle)
        draw.line([x1, y1, x2, y2], fill=_rgba(ring), width=width)

    # --- حلقة واحدة، ثخينة كي تُقرأ صغيرةً ---
    radius = 29 * u
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 outline=_rgba(ring), width=int(4.5 * u))

    base = Image.alpha_composite(base, layer)

    # --- المؤشّر: إبرة **داخل الحلقة**، لا تخترقها ---
    # المراجعة الثالثة: الإبرة الخارجة عن الحلقة بطرف منتفخ كانت تُقرأ
    # **عود ثقاب**، وتكسر الدائرة كسراً لا يخدم شيئاً. حصرُها داخل الحلقة
    # يبقي معنى «القياس» ويحفظ الشكل الدائري نظيفاً.
    if needle_style != "none":
        needle = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        ndraw = ImageDraw.Draw(needle)
        angle = math.radians(-60)
        tip_r = 27 * u                     # ينتهي قبل الحلقة بقليل
        tip = (cx + tip_r * math.cos(angle), cy + tip_r * math.sin(angle))
        ndraw.line([cx, cy, tip[0], tip[1]], fill=_rgba(accent), width=int(5.0 * u))
        r = 3.6 * u
        ndraw.ellipse([tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r],
                      fill=_rgba(accent))
        base = Image.alpha_composite(base, needle)

    # --- المركز: قرص يحمل الحرف. يقطع الإبرة فتبدو خارجةً من تحته ---
    centre = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(centre)
    disc = 24 * u
    cdraw.ellipse([cx - disc, cy - disc, cx + disc, cy + disc],
                  fill=_rgba(palette["field"]))
    base = Image.alpha_composite(base, centre)

    glyph = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glyph)
    if with_meem:
        font = ImageFont.truetype(str(FONT), int(box * 0.36))
        left, top, right, bottom = gdraw.textbbox((0, 0), "م", font=font)
        gdraw.text(
            (cx - (right - left) / 2 - left, cy - (bottom - top) / 2 - top),
            "م", font=font, fill=_rgba(palette["mark"]),
        )
    else:
        r = 9 * u
        gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba(palette["mark"]))
    return Image.alpha_composite(base, glyph)


def field_with_depth(box: int, colour, accent) -> Image.Image:
    """
    خلفية مصمتة **مع وهج واحد** خارج المركز.

    اللون المسطّح تماماً يبدو ميتاً، والتدرّج الكامل صار مبتذلاً. الوهج
    اللامركزي حلٌّ وسط: عمق بلا «تدرّج ستارت-أب».
    """
    base = Image.new("RGBA", (box, box), _rgba(colour))
    glow = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = box * 0.42
    gx, gy = box * 0.30, box * 0.24
    gd.ellipse([gx - r, gy - r, gx + r, gy + r], fill=_rgba(accent, 62))
    return Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(r * 0.5)))


def rounded_mask(size: int, ratio: float = 0.2237) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * ratio), fill=255
    )
    return mask


def build(key: str, size: int = 512, *, with_meem: bool = True,
          needle_style: str = "inner",
          preview_rounded: bool = False) -> Image.Image:
    palette = PALETTES[key]
    big = size * SS
    base = field_with_depth(big, palette["field"], palette["accent"])
    base = draw_astrolabe(base, palette, box=big, with_meem=with_meem,
                          needle_style=needle_style)
    out = base.resize((size, size), Image.LANCZOS)
    if preview_rounded:
        out.putalpha(rounded_mask(size))
    return out


#: اللوحة **المعتمدة**. اختارتها المالكة من خمس بعد ثلاث مراجعات.
ADOPTED = "electric"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in PALETTES:
        build(key, 512, preview_rounded=True).save(OUT / f"astro_{key}.png", "PNG")
        print(f"  ✅ astro_{key:12} — {PALETTES[key]['name_ar']}")
    build("saffron", 512, with_meem=False, preview_rounded=True).save(
        OUT / "astro_saffron_dot.png", "PNG"
    )
    print("  ✅ astro_saffron_dot  — بلا حرف، نقطة مركزية")


if __name__ == "__main__":
    main()
