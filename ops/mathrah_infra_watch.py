# -*- coding: utf-8 -*-
"""
فاحصُ البنية — **يفحص ما لا يقوله النظامُ عن نفسه.**

## لماذا وُجد

من ١١ إلى ١٥ سبتمبر ٢٠٢٦ كان المنفذان ٨٠ و٤٤٣ محجوبَين في جدار `ufw`،
فلم يصل أحدٌ إلى الواجهة ولا إلى التطبيق أربعةَ أيام. والمراقبةُ القائمة
(`mathrah_watch.py`) لم تنبس: هي تقرأ **سجلَّ الأحداث** — أوامرَ وقاطعَ
طوارئ ومطابقة — والمحرّكُ يتصل بالوسيط **خروجاً**، فلا يسجّل السجلُّ شيئاً
عن عجز العالم عن الوصول إلينا.

وأسوأُ من ذلك: `curl` من الخادم إلى عنوانه العامّ **كان ينجح**، لأنّ حركةَ
المضيف إلى نفسه تمرّ عبر `lo` وتقبلها القاعدةُ الأولى قبل أن تصل إلى
`ufw-user-input`. ففحصٌ من الداخل كان سيقول «سليم» وهو أعمى.

فهذا الملفّ يفحص **الشروطَ** لا الأعراض: أتوجد قاعدةُ السماح؟ أتصل حزمٌ
من الخارج فعلاً؟ أتنتهي الشهادة قريباً؟ — أشياءُ لا يعرفها سجلُّ التداول.

## قاعدةُ الإنذار

يُرسل عند **تغيّر الحالة** لا في كل دورة، ويُعيد التذكير كلَّ ٦ ساعات ما
دام العطل قائماً. إنذارٌ يتكرّر كلَّ عشر دقائق يُصمَّت بعد يوم، فيصير
كأنه غير موجود.
"""
from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE = "/opt/mathrah/data/.infra_watch.json"
NOTIFY = "/opt/mathrah/ops/mathrah_notify.sh"
REMIND_AFTER = 6 * 3600          # تذكيرٌ كلَّ ٦ ساعات ما دام العطل قائماً
STALE_TRAFFIC_SECONDS = 6 * 3600  # لا حزمةَ واردةً منذ ٦ ساعات ⇒ شكّ
CERT_WARN_DAYS = 14
HOSTS = ("app.mithrah.fyi", "mithrah.fyi", "167.233.234.236.nip.io")
PORTS_REQUIRED = (80, 443)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return ""


def firewall_findings() -> tuple[list[str], int | None]:
    """
    أتوجد قاعدةُ سماحٍ للمنفذَين؟ وكم حزمةً قبلتها قاعدةُ ٤٤٣؟

    تُقرأ السلسلةُ الفعلية من `nft` لا من `ufw status`: الأولى هي ما يُنفَّذ،
    والثانية عرضٌ قد يتأخّر عن الواقع.
    """
    chain = _run(["nft", "list", "chain", "ip", "filter", "ufw-user-input"])
    if not chain:
        return ["⚠ تعذّرت قراءةُ سلسلة الجدار الناريّ — لا أحكم بالسلامة."], None

    problems: list[str] = []
    for port in PORTS_REQUIRED:
        if not re.search(rf"tcp dport {port}\b.*accept", chain):
            problems.append(
                f"🚨 المنفذ {port} **غيرُ مسموح** في `ufw-user-input` — "
                "لا أحد يصل إلى الواجهة ولا التطبيق."
            )

    counter = None
    m = re.search(r"tcp dport 443\b.*?counter packets (\d+)", chain)
    if m:
        counter = int(m.group(1))
    return problems, counter


def cert_days_left(host: str) -> int | None:
    """أيامٌ تبقى في شهادة المضيف — تُقرأ من المصافحة نفسها لا من ملفّ."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=12) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        return (expiry - datetime.now(timezone.utc)).days
    except Exception:
        return None


def service_findings() -> list[str]:
    out: list[str] = []
    for unit in ("mathrah", "caddy"):
        state = _run(["systemctl", "is-active", unit]).strip()
        if state != "active":
            out.append(f"🚨 الخدمة `{unit}` ليست تعمل (الحالة: {state or 'مجهولة'}).")
    return out


def disk_findings() -> list[str]:
    out = _run(["df", "-P", "/"]).splitlines()
    if len(out) < 2:
        return []
    parts = out[1].split()
    try:
        used_pct = int(parts[4].rstrip("%"))
    except Exception:
        return []
    if used_pct >= 90:
        return [f"⚠ القرصُ ممتلئٌ بنسبة {used_pct}٪ — السجلاتُ والنسخُ في خطر."]
    return []


def load_state() -> dict:
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE)


def main() -> int:
    now = time.time()
    state = load_state()
    problems: list[str] = []

    fw_problems, counter = firewall_findings()
    problems.extend(fw_problems)
    problems.extend(service_findings())
    problems.extend(disk_findings())

    # ── حركةٌ واردةٌ فعلية ──
    # عدّادُ القاعدة يرتفع بكلّ حزمةٍ **خارجية** تُقبل. ثباتُه ساعاتٍ يعني
    # أن أحداً لا يصل — وهو العرَضُ الذي غاب عنّا أربعةَ أيام.
    if counter is not None:
        prev = state.get("c443")
        prev_at = state.get("c443_at", now)
        if prev is None or counter != prev:
            state["c443"], state["c443_at"] = counter, now
        elif now - prev_at > STALE_TRAFFIC_SECONDS:
            hours = int((now - prev_at) / 3600)
            problems.append(
                f"⚠ لم تصل حزمةٌ خارجيةٌ واحدةٌ إلى المنفذ ٤٤٣ منذ {hours} ساعة. "
                "الخدمةُ قد تكون سليمةً والطريقُ إليها مقطوعاً."
            )

    # ── الشهادات ──
    for host in HOSTS:
        days = cert_days_left(host)
        if days is None:
            problems.append(f"⚠ تعذّرت مصافحةُ TLS مع `{host}` — لا أحكم بالسلامة.")
        elif days <= CERT_WARN_DAYS:
            problems.append(f"⚠ شهادةُ `{host}` تنتهي خلال {days} يوماً.")

    key = "|".join(sorted(problems))
    if not problems:
        if state.get("key"):                      # كان هناك عطلٌ وانتهى
            subprocess.run(
                [NOTIFY],
                input="مِثْراة — البنية\n\n✅ عادت الأمورُ سليمة.".encode("utf-8"),
                check=False,
            )
        state["key"] = ""
        state.pop("alerted_at", None)
        save_state(state)
        return 0

    last_key = state.get("key", "")
    last_at = state.get("alerted_at", 0)
    changed = key != last_key
    due = now - last_at > REMIND_AFTER
    if changed or due:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        msg = "مِثْراة — فحصُ البنية · " + stamp + "\n\n" + "\n\n".join(problems)
        subprocess.run([NOTIFY], input=msg.encode("utf-8"), check=False)
        state["alerted_at"] = now
    state["key"] = key
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
