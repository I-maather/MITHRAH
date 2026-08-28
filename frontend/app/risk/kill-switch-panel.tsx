"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import { Card } from "@/components/ui";

const KILL_PHRASE = "أوقف التداول الآن";
const RESET_PHRASE = "أعد تفعيل النظام بعد المراجعة";

export function KillSwitchPanel() {
  const [mode, setMode] = useState<"idle" | "kill" | "reset">("idle");
  const [reason, setReason] = useState("");
  const [phrase, setPhrase] = useState("");
  const [approver, setApprover] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setMessage(null);
    try {
      if (mode === "kill") {
        await apiPost("/api/risk/kill-switch", { reason_ar: reason, confirm_phrase: phrase });
        setMessage("تم إيقاف التداول. لن يُستأنف تلقائياً.");
      } else {
        await apiPost("/api/risk/kill-switch/reset", {
          approved_by: approver,
          reason_ar: reason,
          confirm_phrase: phrase,
          acknowledged_review: acknowledged,
        });
        setMessage("تمت إعادة التفعيل وسُجّلت الموافقة.");
      }
      setMode("idle");
      setReason("");
      setPhrase("");
      setApprover("");
      setAcknowledged(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "فشل الطلب");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Kill Switch" hint="الإيقاف فوري. إعادة التفعيل تتطلب سبباً مكتوباً وعبارة تأكيد كاملة.">
      {message ? (
        <p className="mb-4 rounded-xl bg-surface-sunken px-4 py-3 text-sm">{message}</p>
      ) : null}

      {mode === "idle" ? (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setMode("kill")}
            className="rounded-full bg-stop px-5 py-2.5 text-sm font-medium text-white transition hover:opacity-90"
          >
            إيقاف التداول فوراً
          </button>
          <button
            type="button"
            onClick={() => setMode("reset")}
            className="rounded-full border border-line px-5 py-2.5 text-sm font-medium text-ink-soft transition hover:bg-surface-sunken"
          >
            إعادة التفعيل بعد المراجعة
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {mode === "reset" ? (
            <label className="flex flex-col gap-1 text-sm">
              اسم الموافِقة
              <input
                value={approver}
                onChange={(e) => setApprover(e.target.value)}
                className="rounded-xl border border-line px-3 py-2"
                placeholder="Maather"
              />
            </label>
          ) : null}

          <label className="flex flex-col gap-1 text-sm">
            السبب المكتوب (10 أحرف على الأقل)
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="rounded-xl border border-line px-3 py-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            اكتبي عبارة التأكيد كاملة: «{mode === "kill" ? KILL_PHRASE : RESET_PHRASE}»
            <input
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              className="rounded-xl border border-line px-3 py-2"
            />
          </label>

          {mode === "reset" ? (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              راجعتُ سبب التفعيل وسجل التدقيق قبل إعادة التشغيل.
            </label>
          ) : null}

          <div className="flex gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={submit}
              className="rounded-full bg-ink px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            >
              تأكيد
            </button>
            <button
              type="button"
              onClick={() => setMode("idle")}
              className="rounded-full border border-line px-5 py-2.5 text-sm"
            >
              إلغاء
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
