"use client";

import { useState } from "react";
import { apiPost, ApiError, type ProfileChangeResponse } from "@/lib/api";

const ORDER = ["CAPITAL_PRESERVATION", "BALANCED", "ACTIVE_CONTROLLED"] as const;

export function ProfileSelector({
  effective,
  pending,
  blockedReasonAr,
  options,
}: {
  effective: string;
  pending: string | null;
  blockedReasonAr: string;
  options: { profile: string; name_ar: string; description_ar: string }[];
}) {
  const [target, setTarget] = useState<string>(effective);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProfileChangeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isUpgrade = ORDER.indexOf(target as never) > ORDER.indexOf(effective as never);

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiPost<ProfileChangeResponse>("/api/profiles/select", {
        profile: target,
        owner_confirmed: confirmed,
        owner_reference: "ui",
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "تعذّر تنفيذ الطلب.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        {options.map((o) => {
          const active = target === o.profile;
          return (
            <button
              key={o.profile}
              type="button"
              onClick={() => setTarget(o.profile)}
              className={`rounded-xl border p-3 text-right transition ${
                active
                  ? "border-ink bg-surface-sunken"
                  : "border-line hover:bg-surface-sunken"
              }`}
            >
              <div className="text-sm font-semibold">{o.name_ar}</div>
              <div className="mt-1 text-xs text-ink-faint">{o.description_ar}</div>
              {o.profile === effective ? (
                <div className="mt-2 text-xs text-ok">الملف الفعّال الآن</div>
              ) : null}
            </button>
          );
        })}
      </div>

      {isUpgrade ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-warn">
          <p className="font-semibold">رفع مستوى المخاطرة يتطلب:</p>
          <ul className="mt-1 list-disc space-y-0.5 pr-4">
            <li>تأكيداً صريحاً منك</li>
            <li>لا مركز مفتوح ولا أمر معلّق ولا حالة تنفيذ غير معلومة</li>
            <li>محرك مخاطر سليم بلا قفل خسارة ولا Kill Switch</li>
            <li>مرور ٢٤ ساعة تهدئة قبل أن تصبح المخاطرة الأعلى متاحة</li>
          </ul>
          <label className="mt-3 flex items-center gap-2">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>أؤكد صراحةً طلب رفع مستوى المخاطرة.</span>
          </label>
        </div>
      ) : null}

      {blockedReasonAr ? (
        <p className="text-xs text-stop">سبب عدم السماح حالياً: {blockedReasonAr}</p>
      ) : null}

      <button
        type="button"
        onClick={submit}
        disabled={busy || target === effective}
        className="self-start rounded-full bg-ink px-4 py-2 text-sm text-white disabled:opacity-40"
      >
        {busy ? "جارٍ…" : "تطبيق الملف المختار"}
      </button>

      {result ? (
        <p className={`text-xs ${result.accepted ? "text-ok" : "text-warn"}`}>
          {result.message_ar}
          {result.note_ar ? ` — ${result.note_ar}` : ""}
        </p>
      ) : null}
      {error ? <p className="text-xs text-stop">{error}</p> : null}

      <p className="text-xs text-ink-faint">
        تبديل الملف لا يعيد ضبط أي عدّاد خسارة، ولا يرفع Kill Switch، ولا يفتح التداول
        الحقيقي. الملف الأكثر نشاطاً لا يُجبر النظام على التداول.
      </p>
    </div>
  );
}
