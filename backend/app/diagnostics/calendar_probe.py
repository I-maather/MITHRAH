"""
مسبار تغذية التقويم — **من الخادم نفسه**.

    cd /opt/mathrah/backend
    sudo -u mathrah /opt/mathrah/.venv/bin/python -m app.diagnostics.calendar_probe

## لماذا

العنوان نفسه أعطى ١٢٧ حدثاً من شبكة، و**404 من nginx** من الخادم. فالسؤال
ليس «هل العنوان صحيح» بل «ما الذي يختلف حين يسأل خادمنا». وثلاثة احتمالات
تفسّر ذلك، ولكلٍّ إصلاح مختلف تماماً:

  الهويّة      شبكة التوصيل ترفض العميل بلا `User-Agent`.
  المسار       الصيغة JSON نُقلت والصيغة XML باقية.
  الشبكة       الحجب على نطاق مركز البيانات كلّه، فلا ترويسة تُصلحه.

فيُجرَّب كلٌّ منها مرّة، ويُطبع الرمز والحجم وأوّل النصّ. والفرق بين
السطور هو الجواب — لا التخمين.

## ما لا يفعله

لا يرسل أمراً، ولا يلمس الوسيط، ولا يطبع سرّاً — ولا سرّ في هذه العناوين
أصلاً: تغذية عامة بلا مفتاح.
"""
from __future__ import annotations

from app.providers.faireconomy_calendar import REQUEST_HEADERS

#: مُرشَّحو العنوان. الأوّل هو المستعمَل في الكود.
CANDIDATES = (
    ("JSON هذا الأسبوع", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
    ("XML هذا الأسبوع", "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"),
    ("JSON الأسبوع القادم", "https://nfs.faireconomy.media/ff_calendar_nextweek.json"),
)

VARIANTS = (
    ("بلا هويّة", {}),
    ("بهويّتنا", dict(REQUEST_HEADERS)),
)

OK, BAD, DIM, END = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def main() -> int:
    import httpx

    print("\n\033[1m▸ تغذية التقويم — من هذا الخادم\033[0m\n")
    reachable = False

    for label, url in CANDIDATES:
        print(f"  {DIM}{url}{END}")
        for variant, headers in VARIANTS:
            try:
                response = httpx.get(url, headers=headers, timeout=20)
            except Exception as exc:  # noqa: BLE001
                print(f"    {BAD}⛔{END} {variant:<10} {type(exc).__name__}: {exc}")
                continue

            body = response.text[:60].replace("\n", " ")
            mark = f"{OK}✅{END}" if response.status_code == 200 else f"{BAD}⛔{END}"
            if response.status_code == 200:
                reachable = True
            print(
                f"    {mark} {variant:<10} {response.status_code}"
                f"  {len(response.content)} بايت  ⁦{body}⁩"
            )
        print()

    if reachable:
        print(f"{OK}✅ العنوان يُخدَم من هذا الخادم. قارني السطرين: الفرق هو السبب.{END}\n")
        return 0
    print(f"{BAD}⛔ لا مُرشَّح خُدِم. الحجب على مستوى الشبكة، ولا ترويسة تُصلحه —{END}")
    print(f"{BAD}   يُبحَث عن مصدر آخر، ولا يُرقَّع هذا.{END}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
