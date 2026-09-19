#!/usr/bin/env python3
"""حارسُ حلقةِ القرار — يعيد التشغيل حين تتوقّف النبضة، ولا ينتظر أحداً.

الحارسُ السابق (mathrah_infra_watch) كان **يقيس ولا يتصرّف**. وهذا هو
العيب نفسه الذي يلاحق المشروع: قيمةٌ تُقاس ولا تُقرأ عند موضع الحاجة.
هنا القياسُ يفعل.

القاعدة:
  عمرُ آخر دورة > 300 ثانية  (أو غائب)  →  إعادةُ تشغيل الخدمة.

وحارسٌ للحارس: لا يُعاد التشغيل أكثرَ من مرّة كلّ 15 دقيقة، ولا أكثر من
4 مرّات في الساعة. تجاوزُ ذلك يعني عطلاً لا يُصلحه إعادةُ تشغيل، فيُبلَّغ
ويُترك — لأنّ حلقةَ إعادةِ تشغيلٍ أبديّة أسوأ من توقّفٍ صريح.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HEALTH = "http://127.0.0.1:8000/api/health/ops"
STATE = Path("/opt/mathrah/data/.loop_watch.json")
NOTIFY = Path("/opt/mathrah/ops/mathrah_notify.sh")

STALE_SECONDS = 300
MIN_GAP_SECONDS = 900          # لا إعادةَ تشغيلٍ قبل ربع ساعة من سابقتها
MAX_RESTARTS_PER_HOUR = 4


def notify(message: str) -> None:
    if NOTIFY.exists():
        try:
            subprocess.run([str(NOTIFY), message], timeout=20, check=False)
        except Exception:
            pass
    print(message, flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"restarts": [], "last_alert": 0.0, "was_healthy": True}


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
    except Exception:
        pass


def read_health() -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


def main() -> int:
    now = time.time()
    state = load_state()
    recent = [t for t in state.get("restarts", []) if now - t < 3600]

    health = read_health()

    if health is None:
        age = None
        reason = "الواجهةُ لا تستجيب"
    else:
        loop = health.get("decision_loop") or {}
        age = loop.get("age_seconds")
        reason = "لا نبضةَ مسجّلة" if age is None else f"عمرُ آخر دورة {int(age)} ثانية"

    healthy = age is not None and age <= STALE_SECONDS

    if healthy:
        if not state.get("was_healthy", True):
            notify(f"✅ مِثْراة — حلقةُ القرار عادت. {reason}.")
        state.update({"was_healthy": True, "restarts": recent})
        save_state(state)
        return 0

    # غيرُ سليم.
    if len(recent) >= MAX_RESTARTS_PER_HOUR:
        if now - state.get("last_alert", 0) > 3600:
            notify(
                "⛔️ مِثْراة — الحلقةُ متوقّفة ولا تُصلحها إعادةُ التشغيل "
                f"({len(recent)} محاولات في الساعة). {reason}. تدخّلٌ يدويّ مطلوب."
            )
            state["last_alert"] = now
        state.update({"was_healthy": False, "restarts": recent})
        save_state(state)
        return 1

    last = max(recent) if recent else 0.0
    if now - last < MIN_GAP_SECONDS:
        state.update({"was_healthy": False, "restarts": recent})
        save_state(state)
        return 0  # أُعيد تشغيلها للتوّ — أمهلها

    notify(f"⚠️ مِثْراة — الحلقةُ متوقّفة ({reason}). أُعيد التشغيل الآن.")
    subprocess.run(["systemctl", "restart", "mathrah"], timeout=120, check=False)
    time.sleep(25)

    after = read_health()
    loop_after = (after or {}).get("decision_loop") or {}
    age_after = loop_after.get("age_seconds")
    ok = age_after is not None and age_after <= STALE_SECONDS

    recent.append(now)
    state.update({"was_healthy": ok, "restarts": recent, "last_alert": state.get("last_alert", 0)})
    save_state(state)

    if ok:
        notify(f"✅ مِثْراة — عادت الحلقةُ بعد إعادة التشغيل (عمرُ الدورة {int(age_after)}ث).")
        return 0
    notify("⚠️ مِثْراة — أُعيد التشغيل ولم تعد النبضةُ بعد. سأحاول في الدورة القادمة.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
