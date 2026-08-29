#!/usr/bin/env python3
"""
مقترحات أيقونة — دافئة ومتفائلة، وصادقة في الوقت نفسه.

## ما أخفقت فيه المحاولة الأولى

حوّلتُ «لا تَعِد بربح» إلى **تقشّف بصري**: خلفية شبه سوداء، ونحاسي مطفأ،
وقوسٌ بساقين يقرأه العين شاهدةَ قبر. والقاعدتان مختلفتان تماماً:

    «لا تَعِد بربح»  ⇐ لا سهم أخضر، لا رسم بياني صاعد، لا رموز ثراء
    «كوني دافئة»     ⇐ لون حيّ، شكل مستدير، ضوء

كلاهما مُمكن معاً. الصدق لا يستلزم الكآبة.

## الاتجاه الجديد

حرف **م** بشكله العربي الطبيعي: حلقة مستديرة وذيل. الحلقة شكلٌ ودود بطبعه —
لا زوايا حادة ولا اتجاه صاعد كاذب. والتدرّج اللوني يعطي عمقاً وحياة.

الألوان مستوحاة من **الفجر** لا من المال: بنفسجي عميق إلى كهرماني، أو
فيروزي إلى ذهبي. لا أخضر «الأرباح»، ولا أزرق مؤسسي يقلّد الوسيط.

    python3 scripts/icon_concepts.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "assets" / "concepts"
SS = 4                      # تكبير للرسم ثم تصغير — لتنعيم الحواف


# ---------------------------------------------------------------------------
# لوحات الألوان — كلها دافئة، ولا واحدة منها «أخضر المال»
# ---------------------------------------------------------------------------

PALETTES = {
    "dawn": {
        "name_ar": "الفجر",
        "bg": [(46, 26, 71), (192, 64, 92), (247, 163, 76)],
        "mark": (255, 246, 232),
        "accent": (255, 209, 122),
    },
    "amber": {
        "name_ar": "كهرمان",
        "bg": [(120, 45, 30), (214, 122, 44), (250, 200, 106)],
        "mark": (255, 251, 242),
        "accent": (255, 233, 189),
    },
    "teal_gold": {
        "name_ar": "فيروز وذهب",
        "bg": [(14, 74, 82), (26, 133, 128), (240, 190, 92)],
        "mark": (255, 252, 244),
        "accent": (255, 224, 150),
    },
    "sunrise": {
        "name_ar": "شروق",
        "bg": [(255, 138, 76), (255, 190, 92), (255, 236, 179)],
        "mark": (72, 34, 22),
        "accent": (140, 62, 34),
    },
    "plum": {
        "name_ar": "توتي",
        "bg": [(63, 24, 84), (139, 46, 132), (233, 122, 122)],
        "mark": (255, 244, 240),
        "accent": (255, 205, 158),
    },
}


def linear_gradient(size: int, stops: list[tuple[int, int, int]], angle: float = 135.0):
    """
    تدرّج خطّي بزاوية. التدرّج ليس زينة: السطح المسطّح الواحد يبدو ميتاً في
    شبكة الأيقونات، والتدرّج يعطي عمقاً يُقرأ حتى في 60 بكسل.
    """
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    # أطول إسقاط ممكن على محور التدرّج، للتطبيع.
    span = abs(dx) * size + abs(dy) * size

    segments = len(stops) - 1
    for y in range(size):
        for x in range(size):
            t = ((x * dx + y * dy) + (span - (dx * size + dy * size)) / 2) / span
            t = min(1.0, max(0.0, t))
            pos = t * segments
            i = min(segments - 1, int(pos))
            local = pos - i
            a, b = stops[i], stops[i + 1]
            pixels[x, y] = (
                int(a[0] + (b[0] - a[0]) * local),
                int(a[1] + (b[1] - a[1]) * local),
                int(a[2] + (b[2] - a[2]) * local),
            )
    return image


def soft_glow(size: int, centre: tuple[float, float], radius: float,
              colour: tuple[int, int, int], strength: float = 0.55) -> Image.Image:
    """
    وهج ناعم خلف العلامة. يعطي إحساس الضوء لا اللمعان المعدني.
    """
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = centre
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(*colour, int(255 * strength)),
    )
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


#: خط الأيقونة. **الكوفي** لا Naskh: حلقته مستديرة وذيله مستقيم، فيُقرأ
#: ودوداً وواضحاً حتى في 60 بكسل. وNaskh مائل ومزوّى، يبدو قاسياً في مربّع.
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / \
    "NotoKufiArabic-Bold.ttf"


def meem_layer(box: int, colour, *, ratio: float = 0.62,
               nudge_y: float = -0.02) -> Image.Image:
    """
    حرف **م** من خط عربي حقيقي، لا مرسوماً ببدائيات.

    المحاولتان السابقتان رسمتاه يدوياً فقُرِئ مرة **مفتاحاً** ومرة حرف `g`
    لاتينياً. الحرف العربي له نسب لا تُخمَّن — والخط المصمَّم يعرفها.

    التوسيط بمربّع الحدود الفعلي لا بمقياس الخط: `م` لا صعود له ولا نزول،
    فالتوسيط بمقاييس السطر يتركه عائماً في الأعلى.
    """
    layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(FONT_PATH), int(box * ratio))
    left, top, right, bottom = draw.textbbox((0, 0), "م", font=font)
    draw.text(
        (box / 2 - (right - left) / 2 - left,
         box / 2 - (bottom - top) / 2 - top + box * nudge_y),
        "م", font=font, fill=(*colour, 255),
    )
    return layer


def rounded_mask(size: int, radius_ratio: float = 0.2237) -> Image.Image:
    """
    قناع الزوايا المستديرة بنسبة Apple التقريبية — **للمعاينة فقط**.
    الأيقونة المُسلَّمة إلى المتجر تبقى مربّعة، وiOS يقصّها بنفسه.
    """
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255
    )
    return mask


def build(palette_key: str, size: int = 512, *, glow: bool = True,
          preview_rounded: bool = False) -> Image.Image:
    palette = PALETTES[palette_key]
    big = size * SS

    base = linear_gradient(big, palette["bg"], angle=125).convert("RGBA")

    if glow:
        base = Image.alpha_composite(
            base,
            soft_glow(big, (big / 2, big * 0.42), big * 0.30, palette["accent"], 0.42),
        )

    base = Image.alpha_composite(base, meem_layer(big, palette["mark"]))

    out = base.resize((size, size), Image.LANCZOS)
    if preview_rounded:
        out.putalpha(rounded_mask(size))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in PALETTES:
        image = build(key, 512, preview_rounded=True)
        image.save(OUT / f"{key}.png", "PNG")
        print(f"  ✅ {key:10} — {PALETTES[key]['name_ar']}")


if __name__ == "__main__":
    main()
