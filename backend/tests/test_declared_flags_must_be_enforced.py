"""
**عَلَمٌ يدّعي المنعَ ولا موضعَ إنفاذٍ له — عطلٌ مفتوحٌ مُوثَّق.**

## ما قِيس (٢٠٢٦-٠٩-١٣ ثمّ ٢٠٢٦-٠٩-١٥)

`allow_overnight` و`allow_weekend_hold` معلَنان `False` في الأوضاع الأربعة،
ويُصدَّران إلى شاشة الجوال، **ولا يُقرآن في أيّ مسارٍ حيّ**. الإنفاذُ الوحيد
في `app/strategies/backtest.py:346` وهو يقرأ إعدادَ الاختبار لا الدستور.

والمركزان المفتوحان يبيتان ويعبران عطلةَ الأسبوع فعلاً.

## ولماذا هذا أخطرُ من وسمٍ خاطئ

`test_no_borrow_cost_exists_in_the_cfd_model` يقول إن `overnight_cost`
«صفرٌ بلا مبيت»، و`test_no_position_survives_the_night_or_the_weekend`
يبني عليه أن الوسيط لا يفرّق بين البيع والشراء عدديّاً — **وعلى ذلك فُتح
البيع** في الدستور 0.3.0.

فالسلسلة: عَلَمٌ لا يُنفَّذ ⇐ كلفةُ تبييتٍ غيرُ محسوبة ⇐ تماثلٌ مفترَض بين
الجهتين ⇐ إذنٌ بالبيع. وكلُّ صفقاتنا المفتوحة بيع.

## لماذا `xfail` لا `assert`

الحالةُ الراهنة عطلٌ حقيقيّ، فلا يصحّ أن يمرّ الاختبار. ولا يصحّ أن تبقى
الحزمةُ حمراء فتُعمي عن أعطالٍ جديدة. فيُسجَّل `xfail(strict=True)`:
يبقى الأثرُ مرئياً في كل تشغيل، **ويوم يُكتب الإنفاذُ فعلاً يصير XPASS
ويُسقط الحزمة** — فيُقرأ هذا الملفّ ويُحذف الوسم. لا نسيانَ في الاتجاهين.

القرارُ المطلوب من المالكة (موثَّق في `claude/OPEN-OVERNIGHT-HOLD-2026-09-13.md`):
إمّا إنفاذُ الخروج الزمنيّ عبر `Capability.TIME_EXIT` بدليلها، وإمّا إعلانُ
المبيت مسموحاً مع **إعادة حساب كلفة التبييت** ومراجعةِ إذن البيع المبنيّ عليها.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.risk.constitution import MODE_SPECS

APP = Path(__file__).resolve().parents[1] / "app"
FLAGS = ("allow_overnight", "allow_weekend_hold")

#: مواضعُ تعريفٍ ونقلٍ وعرض — لا إنفاذ. `backtest.py` يقرأ إعدادَ الاختبار
#: (`self.config`) لا الدستور، فوجودُه هناك لا يجعل الحدَّ نافذاً على صفقةٍ حيّة.
DECLARATION_ONLY = (
    "risk/constitution.py",
    "profiles/__init__.py",
    "mobile/state.py",
    "strategies/backtest.py",
)


def live_readers(flag: str) -> list[str]:
    """كلُّ سطرٍ يقرأ العَلَم خارج مواضع الإعلان."""
    found: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path).split("app/", 1)[-1]
        if any(rel.endswith(skip) for skip in DECLARATION_ONLY):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if flag not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(rf"^{flag}\s*[:=]", stripped):
                continue
            found.append(f"{rel}:{i}")
    return found


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.xfail(
    strict=True,
    reason="عطلٌ مفتوح: العَلَم يدّعي المنع ولا موضعَ إنفاذٍ له في المسار الحيّ. "
    "يُنتظَر قرارُ المالكة — إنفاذٌ بدليل، أو إعلانُ الإباحة مع إعادة حساب "
    "كلفة التبييت ومراجعة إذن البيع.",
)
def test_a_flag_that_forbids_must_have_a_place_that_enforces_it(flag: str) -> None:
    forbidding = [m.value for m, s in MODE_SPECS.items() if getattr(s, flag) is False]
    if not forbidding:
        pytest.skip(f"لا وضعَ يدّعي المنع بـ`{flag}` — لا شيءَ يُحرَس.")
    readers = live_readers(flag)
    assert readers, (
        f"`{flag}` معلَنٌ `False` (أي «ممنوع») في: {'، '.join(forbidding)} — "
        f"ولا سطرَ واحدٌ في المسار الحيّ يقرؤه. حارسٌ يُعلَن ولا يمنع أسوأ "
        f"من غيابه: يُطمئن، ويُعرَض في الجوال، ويُبنى عليه أنّ كلفة التبييت صفر."
    )


def test_the_exclusion_list_is_honest() -> None:
    """
    المُستثنياتُ ليست راحة: كلُّ ملفٍّ فيها يجب أن يوجد ويذكر العَلَم.
    فلو نُقل الإنفاذُ إليه أو حُذف، لا يمرّ الاستثناءُ بصمت.
    """
    for rel in DECLARATION_ONLY:
        path = APP / rel
        assert path.exists(), f"مُستثنىً لا وجود له: {rel}"
        body = path.read_text(encoding="utf-8")
        assert any(f in body for f in FLAGS), f"{rel} مُستثنىً ولا يذكر العَلَمَين."


def test_the_open_defect_is_recorded_where_the_owner_reads_it() -> None:
    """الوثيقةُ التي تحمل القرارَ المطلوب — اسمُها جزءٌ من هذا العقد."""
    assert "OPEN-OVERNIGHT-HOLD" in Path(__file__).read_text(encoding="utf-8")
