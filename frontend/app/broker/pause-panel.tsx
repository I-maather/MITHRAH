"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import { Card } from "@/components/ui";

const RESUME_PHRASE = "ارفع الإيقاف المحلي";

export function PausePanel({
  paused,
  killSwitchActive,
}: {
  paused: boolean;
  killSwitchActive: boolean;
}) {
  const [mode, setMode] = useState<"idle" | "pause" | "resume">("idle");
  const [reason, setReason] = useState("");
  const [phrase, setPhrase] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setMessage(null);
    try {
      if (mode === "pause") {
        await apiPost("/api/trading/pause", { reason_ar: reason });
        setMessage("أُوقف التداول محلياً.");
      } else {
        const result = await apiPost<{ note_ar: string }>("/api/trading/resume", {
          reason_ar: reason,
          confirm_phrase: phrase,
        });
        setMessage(result.note_ar);
      }
      setMode("idle");
      setReason("");
      setPhrase("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "فشل الطلب");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="الإيقاف المحلي"
      hint="الإيقاف فوري ولا يحتاج تأكيداً. رفعه لا يفعّل التداول الحقيقي بأي حال."
    >
      {message ? (
        <p className="mb-4 rounded-xl bg-surface-sunken px-4 py-3 text-sm">{message}</p>
      ) : null}

      {mode === "idle" ? (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setMode("pause")}
            disabled={paused}
            className="rounded-full bg-stop px-5 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
          >
            {paused ? "موقوف محلياً بالفعل" : "أوقف التداول محلياً"}
          </button>
          <button
            type="button"
            onClick={() => setMode("resume")}
            disabled={!paused || killSwitchActive}
            className="rounded-full border border-line px-5 py-2.5 text-sm font-medium text-ink-soft transition hover:bg-surface-sunken disabled:opacity-40"
          >
            {killSwitchActive ? "Kill Switch مفعّل — الرفع ممنوع" : "ارفع الإيقاف المحلي"}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            السبب المكتوب
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="rounded-xl border border-line px-3 py-2"
            />
          </label>

          {mode === "resume" ? (
            <label className="flex flex-col gap-1 text-sm">
              اكتبي عبارة التأكيد كاملة: «{RESUME_PHRASE}»
              <input
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                className="rounded-xl border border-line px-3 py-2"
              />
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
