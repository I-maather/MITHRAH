"""
إنزال الهوية على التطبيق — خطوة واحدة، تتحقّق قبل أن تكتب.

    backend/.venv/bin/python scripts/land_identity.py            # فحص فقط
    backend/.venv/bin/python scripts/land_identity.py --apply    # فحصٌ ثم كتابة

## لماذا يتحقّق أولاً

هذه الملفات كُتبت بلا اتصال بجهازك، اعتماداً على ما رأيتُه من نسق التصميم
لا على قراءةٍ كاملة له. فقد تختلف أسماء مثل `spacing.md` أو `variant`
المتاحة. والسكربت يقرأ نسقك الفعلي ويقارن **قبل** أن ينسخ حرفاً واحداً؛
وإن اختلف شيء توقّف وطبع الفرق ولم يكتب. ملفٌّ لا يُبنى أفضل من ملفٍّ
يُكسر البناء ثم يُبحث عن سببه.

## ما يفعله عند `--apply`

  ١  خطّا أميري إلى `mobile/assets/fonts/`
  ٢  أصول العلامة إلى `mobile/assets/brand/`
  ٣  أيقونات التطبيق إلى `mobile/assets/`
  ٤  المكوّنات الثلاثة إلى `mobile/src/components/`
  ٥  `display` في `tokens.ts` من ReemKufi إلى Amiri، مع مفتاح `logo` مستقلّ
  ٦  تسجيل خطّي أميري في `_layout.tsx`
  ٧  تصدير المكوّنات من `components/index.ts`

ولا يلمس شاشةً واحدة: تركيب المكوّنات في الشاشات خطوة تالية بعد أن تخضرّ
الاختبارات.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "_identity_bundle"      # مجلّد الحزمة المفكوكة
MOBILE = REPO / "mobile"

APPLY = "--apply" in sys.argv

OK, BAD = "\033[32m", "\033[31m"
DIM, END = "\033[2m", "\033[0m"


def ok(m): print(f"  {OK}✅{END} {m}")
def bad(m): print(f"  {BAD}⛔{END} {m}")
def dim(m): print(f"  {DIM}{m}{END}")


problems: list[str] = []


def need(cond: bool, msg: str) -> bool:
    (ok if cond else bad)(msg)
    if not cond:
        problems.append(msg)
    return cond


def main() -> None:
    print("\n\033[1m▸ ١ · وجود الملفات\033[0m")
    need(BUNDLE.exists(), f"حزمة الهوية: {BUNDLE}")
    tokens_p = MOBILE / "src" / "theme" / "tokens.ts"
    text_p = MOBILE / "src" / "components" / "Text.tsx"
    index_p = MOBILE / "src" / "components" / "index.ts"
    layout_p = MOBILE / "app" / "_layout.tsx"
    for p in (tokens_p, text_p, index_p, layout_p):
        need(p.exists(), f"{p.relative_to(REPO)}")
    if problems:
        return finish()

    tokens = tokens_p.read_text(encoding="utf-8")
    text_src = text_p.read_text(encoding="utf-8")
    # الألوان تعيش في colors.ts لا tokens.ts. البحث في tokens وحده كان يُبلّغ
    # عن غياب تسعة ألوان موجودة — فحصٌ يكذب أسوأ من فحصٍ لا يوجد.
    colors_p = MOBILE / "src" / "theme" / "colors.ts"
    theme_src = tokens + (colors_p.read_text(encoding="utf-8") if colors_p.exists() else "")

    print("\n\033[1m▸ ٢ · مطابقة نسق التصميم\033[0m")
    # المسافات التي تستعملها المكوّنات الجديدة
    for key in ("xs", "sm", "md"):
        need(
            re.search(rf"\b{key}\s*:", tokens) is not None,
            f"spacing.{key} موجود",
        )
    # الألوان التي تستعملها
    for key in (
        "border", "background", "accent",
        "textPrimary", "textSecondary", "textTertiary",
        "positive", "negative", "caution",
    ):
        need(re.search(rf"\b{key}\s*:", theme_src) is not None, f"colors.{key} موجود")
    # صيغ النصّ
    for v in ("caption", "bodyStrong"):
        need(re.search(rf"\b{v}\s*:", tokens) is not None, f"typography.{v} موجود")
    # الخاصيات التي تُمرَّر إلى Text
    for prop in ("tabular", "tone", "variant"):
        need(f"{prop}" in text_src, f"Text يقبل «{prop}»")

    print("\n\033[1m▸ ٣ · حالة الشجرة\033[0m")
    need("ReemKufi" in tokens, "tokens.ts يعرّف ReemKufi حالياً (سيُنقل إلى logo)")

    if problems:
        return finish()

    if not APPLY:
        print(f"\n{DIM}  فحصٌ فقط. أعيدي التشغيل بـ --apply للكتابة.{END}\n")
        return

    # ---------------------------------------------------------------
    print("\n\033[1m▸ ٤ · النسخ\033[0m")
    pairs = [
        (BUNDLE / "Amiri-Regular.ttf", MOBILE / "assets/fonts/Amiri-Regular.ttf"),
        (BUNDLE / "Amiri-Bold.ttf", MOBILE / "assets/fonts/Amiri-Bold.ttf"),
        (BUNDLE / "icons/icon.png", MOBILE / "assets/icon.png"),
        (BUNDLE / "icons/adaptive-icon.png", MOBILE / "assets/adaptive-icon.png"),
        (BUNDLE / "icons/splash-icon.png", MOBILE / "assets/splash-icon.png"),
        (BUNDLE / "icons/favicon.png", MOBILE / "assets/favicon.png"),
    ]
    for name in ("Hadd.tsx", "EmptyState.tsx", "Wordmark.tsx"):
        pairs.append((BUNDLE / "components" / name, MOBILE / "src/components" / name))
    for p in (BUNDLE / "assets" / "brand").glob("*.png"):
        pairs.append((p, MOBILE / "assets/brand" / p.name))
    for p in (BUNDLE / "brand").glob("*.svg"):
        pairs.append((p, REPO / "brand" / p.name))

    for src, dst in pairs:
        if not src.exists():
            bad(f"مفقود من الحزمة: {src.name}")
            problems.append(src.name)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        ok(str(dst.relative_to(REPO)))
    if problems:
        return finish()

    # ---------------------------------------------------------------
    print("\n\033[1m▸ ٥ · تحويل display إلى أميري\033[0m")
    new_tokens = tokens
    if "logo:" not in new_tokens:
        new_tokens = new_tokens.replace(
            "  display: 'ReemKufi',",
            "  /** العناوين وجُمل الحكم. نسخيٌّ مفتوح الحروف، عربيٌّ لا مترجَم. */\n"
            "  display: 'Amiri',\n"
            "  /** العلامة وحدها — ولا يدخل نصّ الواجهة أبداً. */\n"
            "  logo: 'ReemKufi',",
            1,
        )
    changed = new_tokens != tokens
    need(changed, "استُبدل display: 'ReemKufi' بـ display: 'Amiri' + logo")
    if changed:
        tokens_p.write_text(new_tokens, encoding="utf-8")

    print("\n\033[1m▸ ٦ · تسجيل خطّي أميري\033[0m")
    lay = layout_p.read_text(encoding="utf-8")
    if "Amiri" not in lay:
        lay2 = lay.replace(
            "    ReemKufi: require('../assets/fonts/ReemKufi.ttf'),",
            "    ReemKufi: require('../assets/fonts/ReemKufi.ttf'),\n"
            "    Amiri: require('../assets/fonts/Amiri-Regular.ttf'),\n"
            "    'Amiri-Bold': require('../assets/fonts/Amiri-Bold.ttf'),",
            1,
        )
        need(lay2 != lay, "أُضيف أميري إلى useFonts")
        if lay2 != lay:
            layout_p.write_text(lay2, encoding="utf-8")
    else:
        ok("أميري مسجَّل مسبقاً")

    print("\n\033[1m▸ ٧ · التصدير\033[0m")
    idx = index_p.read_text(encoding="utf-8")
    add = "".join(
        f"export * from './{n}';\n"
        for n in ("Hadd", "EmptyState", "Wordmark")
        if f"'./{n}'" not in idx
    )
    if add:
        index_p.write_text(idx.rstrip() + "\n" + add, encoding="utf-8")
        ok("صُدِّرت Hadd و EmptyState و Wordmark")
    else:
        ok("مُصدَّرة مسبقاً")

    finish()


def finish() -> None:
    print()
    if problems:
        print(f"{BAD}⛔ توقّف عند {len(problems)} مشكلة. راجعيها أعلاه.{END}\n")
        sys.exit(1)
    print(f"{OK}✅ تمّ.{END}")
    print(f"{DIM}   التالي:  cd mobile && npx jest{END}\n")


if __name__ == "__main__":
    main()
