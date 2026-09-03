"""
«للآن ما تم التداول» — سؤالٌ لم يكن في النظام ما يجيبه.

## العطل

بعد يومٍ كاملٍ من التشغيل التجريبي سألت المالكة: لماذا لم يتداول بعد؟
ولم يكن في أي نداء ما يجيب:

* `/api/today` يعرض **آخر** قرارٍ وحده — لقطةً لا تاريخاً.
* `/api/health` يعرض `scheduler_ok: true`. وهي صادقةٌ تماماً عن مجدولٍ
  **لم يدر ولا مرّة**: الراية تعني «لا خطأ مسجّل»، لا «عمل».

فالسؤال الأول — هل دارت حلقة القرار أصلاً؟ — لم يكن له جواب في الواجهة،
لا لها ولا لي. وكل تفسيرٍ يُقدَّم قبل هذا الجواب تخمينٌ مهما بدا محكماً.

وهذا صنف اليوم في أهدأ صوره: **رايةٌ تُقرأ إجابةً عن سؤالٍ لم تُسأل**.

## الإصلاح

`/api/health` يعرض `scheduler` كاملاً: اسم المهمة، وعدد الدورات، وعدد
الإخفاقات، وآخر دورة، والتالية، وأوّل خطأ. و`scripts/why_no_trade.sh`
يقرأ الأربعة بالترتيب ولا يقفز عن أوّلها.

## ما يحرسه هذا الملف

أن العدد يُعرض (لا الراية وحدها)، وأن السكربت يبقى **قارئاً لا فاعلاً**.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from app.scheduling import JobKind, SafeScheduler

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "why_no_trade.sh"
SOURCE = SCRIPT.read_text(encoding="utf-8")


class FakeBroker:
    name = "FAKE"
    is_live = False

    def health_check(self) -> bool:
        return False


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.state import build_system
    from app.main import app, system as system_dep

    state = build_system()
    state.broker = FakeBroker()  # type: ignore[assignment]
    app.dependency_overrides[system_dep] = lambda: state
    try:
        yield TestClient(app), state
    finally:
        app.dependency_overrides.pop(system_dep, None)


# ---------------------------------------------------------------------------
# ١ · العدد يُعرض، لا الراية وحدها
# ---------------------------------------------------------------------------
def test_health_exposes_every_job_with_its_run_count(client):
    api, state = client
    state.scheduler = SafeScheduler()
    state.scheduler.register(
        "DECISION", kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=60), func=lambda: None,
    )
    payload = api.get("/api/health").json()
    assert "scheduler" in payload, "حالة المجدول غير معروضة — السؤال الأول بلا جواب"
    jobs = payload["scheduler"]
    assert jobs and jobs[0]["name"] == "DECISION"
    for key in ("runs", "failures", "last_run_riyadh", "next_run_riyadh", "last_error"):
        assert key in jobs[0], f"الحقل {key} مفقود"


def test_a_job_that_never_ran_is_visible_as_zero_not_hidden(client):
    """
    **جوهر العطل.** `scheduler_ok` تبقى `True` لمجدولٍ لم يدر — لأن لا خطأ
    فيه. والعدد وحده يفرّق بين «يعمل بلا فرصة» و«لا يعمل».
    """
    api, state = client
    state.scheduler = SafeScheduler()
    state.scheduler.register(
        "DECISION", kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=60), func=lambda: None,
    )
    payload = api.get("/api/health").json()
    assert payload["scheduler_ok"] is True          # الراية تقول «سليم»…
    assert payload["scheduler"][0]["runs"] == 0     # …والعدد يقول «لم يدر»
    assert payload["scheduler"][0]["last_run_riyadh"] is None


def test_the_count_actually_moves_when_the_job_runs(client):
    """حارسٌ للحارس: عددٌ مثبَّتٌ على صفر يمرّ الفحص السابق ولا يعني شيئاً."""
    api, state = client
    state.scheduler = SafeScheduler()
    state.scheduler.register(
        "DECISION", kind=JobKind.READ_ONLY,
        interval=timedelta(seconds=0), func=lambda: None,
    )
    state.scheduler.tick()
    payload = api.get("/api/health").json()
    assert payload["scheduler"][0]["runs"] >= 1
    assert payload["scheduler"][0]["last_run_riyadh"] is not None


# ---------------------------------------------------------------------------
# ٢ · السكربت يقرأ ولا يفعل
# ---------------------------------------------------------------------------
def test_the_script_exists_and_is_valid_bash():
    assert SCRIPT.is_file()
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_every_embedded_python_block_parses_on_this_interpreter():
    """
    **فخٌّ حقيقي وقعتُ فيه أثناء الكتابة:** شرطةٌ مائلة داخل f-string خطأٌ
    نحويّ قبل بايثون 3.12. والسكربت يُشغَّل على ماكها لا على الخادم — فقد
    ينكسر عندها ويعمل عندي. فتُفحَص كلُّ كتلةٍ نحويّاً هنا.
    """
    blocks = re.findall(r"python3 -c '\n(.*?)\n'", SOURCE, re.S)
    assert len(blocks) >= 4, f"توقّعت أربع كتل على الأقل، وجدت {len(blocks)}"
    for index, block in enumerate(blocks):
        try:
            ast.parse(block)
        except SyntaxError as exc:  # pragma: no cover - يظهر في الرسالة
            pytest.fail(f"الكتلة {index} لا تُحلَّل على بايثون {sys.version_info[:2]}: {exc}")


def test_the_script_never_writes_to_the_system():
    """قراءةٌ فقط: لا أمر، ولا استئناف، ولا إيقاف، ولا تعديل إعداد."""
    commands = "\n".join(
        line for line in SOURCE.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("-X POST", "-X PUT", "-X DELETE", "systemctl", "/api/trading/",
                      "/api/risk/kill-switch", "/api/profiles/select"):
        assert forbidden not in commands, f"السكربت يفعل شيئاً: {forbidden}"


def test_the_script_asks_the_four_questions_in_order():
    """الترتيب جزءٌ من الجواب: تفسيرٌ قبل «هل دارت الحلقة؟» تخمين."""
    order = [
        "هل دارت حلقة القرار",
        "هل كانت بوابةٌ عامة مغلقة",
        "ماذا رأى على كل أداة",
        "توزيع أسباب الرفض",
    ]
    positions = [SOURCE.index(q) for q in order]
    assert positions == sorted(positions), "ترتيب الأسئلة اختلّ"


def test_an_unreadable_server_is_not_reported_as_healthy():
    commands = "\n".join(
        line for line in SOURCE.splitlines() if not line.lstrip().startswith("#")
    )
    assert "لا أدّعي شيئاً عن حالته — لم أقرأ" in commands
    assert "لا قراءة ولا حكم" in commands
