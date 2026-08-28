import { apiGet, type IntelligenceState } from "@/lib/api";
import { Card, ErrorBox, Pill, Stat, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

function StageIcon({ passed }: { passed: boolean | null }) {
  if (passed === null) return <Pill>لم تُشغَّل</Pill>;
  return passed ? <Pill tone="ok">اجتازت</Pill> : <Pill tone="stop">رفضت</Pill>;
}

export default async function IntelligencePage() {
  let state: IntelligenceState;
  try {
    state = await apiGet<IntelligenceState>("/api/intelligence");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  const decision = state.decision ?? "لم تُشغَّل دورة";
  const isNoTrade = state.decision === "NO_TRADE";

  return (
    <div className="flex flex-col gap-5">
      <Card
        title="القرار"
        hint="الامتناع قرار صحيح. هذه الصفحة تشرح لماذا، لا تكتفي بإظهار «لا شيء»."
      >
        <div className="mb-5 flex flex-wrap gap-2">
          <Pill tone={state.decision === "TRADE" ? "ok" : isNoTrade ? "warn" : "stop"}>
            {decision}
          </Pill>
          {state.reason_code ? <Pill>{state.reason_code}</Pill> : null}
          {state.profile ? <Pill>الملف: {state.profile}</Pill> : null}
          {state.snapshot_id ? (
            <Pill>لقطة: {state.snapshot_id.slice(0, 12)}</Pill>
          ) : null}
        </div>

        <p className="whitespace-pre-line text-sm leading-relaxed text-ink-soft">
          {state.explanation_ar || state.reason_ar || "لم تُشغَّل دورة تحليل بعد."}
        </p>

        {state.decided_at_utc ? (
          <p className="mt-4 text-xs text-ink-faint">
            وقت آخر تحديث: <span dir="ltr">{state.decided_at_utc}</span>
          </p>
        ) : null}
      </Card>

      <Card title="مراحل التحليل السبع عشرة">
        <Table
          empty="لا مراحل."
          head={["#", "المرحلة", "الحالة", "إلزامية", "التفصيل"]}
          rows={state.stages.map((s, i) => [
            String(i + 1),
            s.name_ar,
            <StageIcon key={s.stage} passed={s.passed} />,
            s.mandatory === false ? "لا" : "نعم",
            s.detail_ar ?? "—",
          ])}
        />
      </Card>

      {state.regime || state.timeframes ? (
        <Card title="السوق والأطر الزمنية">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="حالة السوق" value={state.regime?.name_ar ?? "غير معلوم"} />
            <Stat
              label="النظام الأساسي (D1)"
              value={state.timeframes?.primary_regime_trend ?? "—"}
            />
            <Stat
              label="الاتجاه الهيكلي (H4)"
              value={state.timeframes?.structural_trend ?? "—"}
            />
            <Stat label="إطار الدخول (M15)" value={state.timeframes?.entry_trend ?? "—"} />
          </div>
          {state.regime ? (
            <p className="mt-4 text-xs text-ink-faint">{state.regime.reason_ar}</p>
          ) : null}
          {state.timeframes?.incomplete?.length ? (
            <p className="mt-2 text-xs text-stop">
              أطر ناقصة: {state.timeframes.incomplete.join("، ")}
            </p>
          ) : null}
        </Card>
      ) : null}

      {state.fundamentals ? (
        <Card
          title="الحالة الاقتصادية"
          hint="مُدخَل واحد ضمن مدخلات — لا يعتمد صفقة وحده."
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="انحياز EUR/USD" value={state.fundamentals.relative_bias_ar} />
            <Stat label="اكتمال البيانات" value={state.fundamentals.completeness} />
            <Stat
              label="صالح للاستعمال"
              value={state.fundamentals.usable ? "نعم" : "لا"}
              tone={state.fundamentals.usable ? "ok" : "warn"}
            />
          </div>
          {state.fundamentals.unknown_fields.length ? (
            <p className="mt-3 text-xs text-ink-faint">
              حقول غير معلومة: {state.fundamentals.unknown_fields.join("، ")}
            </p>
          ) : null}
        </Card>
      ) : null}

      {state.score ? (
        <Card
          title={`درجة الجودة — ${state.score.total} / ${state.score.max}`}
          hint="كل نقطة لها مصدر. فشل بوابة إلزامية لا يُعوَّض بأي درجة."
        >
          {state.score.has_mandatory_failure ? (
            <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-stop">
              <p className="font-semibold">فشل إلزامي — الدرجة لا تُستشار أصلاً:</p>
              <ul className="mt-1 list-disc space-y-0.5 pr-4">
                {state.score.mandatory_failures.map((f) => (
                  <li key={f.code}>{f.reason_ar}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <Table
            empty="لا بنود."
            head={["الفئة", "الممنوح", "الأقصى", "السبب", "المصدر"]}
            rows={state.score.lines.map((l) => [
              l.category_ar,
              String(l.awarded),
              String(l.maximum),
              l.reason_ar,
              l.source_ar,
            ])}
          />
        </Card>
      ) : null}

      {state.contradictions && state.contradictions.count > 0 ? (
        <Card
          title={`التناقضات — ${state.contradictions.count}`}
          hint="لكل تناقض حلّ مكتوب مسبقاً. لا يُطلب حكم حدسي من نموذج لغوي."
        >
          <Table
            empty="لا تناقضات."
            head={["الطرف الأول", "الطرف الثاني", "الخطورة", "الحل الحتمي", "يمنع؟"]}
            rows={state.contradictions.items.map((c) => [
              c.side_a_ar,
              c.side_b_ar,
              c.severity_ar,
              c.resolution_ar,
              c.blocks_trading ? "نعم" : "لا",
            ])}
          />
        </Card>
      ) : null}

      {state.verification ? (
        <Card title="المراجع المستقل">
          <div className="mb-3 flex flex-wrap gap-2">
            <Pill tone={state.verification.passed ? "ok" : "stop"}>
              {state.verification.passed ? "مطابق" : "اختلاف"}
            </Pill>
          </div>
          <p className="text-sm text-ink-soft">{state.verification.reason_ar}</p>
          {state.verification.mismatches.length ? (
            <p className="mt-2 text-xs text-stop">
              حقول مختلفة: {state.verification.mismatches.join("، ")}
            </p>
          ) : null}
        </Card>
      ) : null}

      <Card
        title="جودة البيانات والمزوّدون"
        hint="المزوّد غير المُعدّ يظهر باسمه الدقيق ويمنع الأهلية الحقيقية."
      >
        <div className="mb-4">
          <Pill tone={state.providers.live_eligible_by_providers ? "ok" : "stop"}>
            {state.providers.live_eligible_by_providers
              ? "كل المزوّدين الإلزاميين مُعدّون"
              : "مزوّدون إلزاميون ناقصون"}
          </Pill>
        </div>
        <Table
          empty="لا مزوّدين."
          head={["المزوّد", "الحالة", "الاسم", "ملاحظة"]}
          rows={state.providers.providers.map((p) => [
            p.kind,
            p.configured ? <Pill tone="ok" key={p.kind}>مُعدّ</Pill> : <Pill tone="stop" key={p.kind}>غير مُعدّ</Pill>,
            p.name,
            p.note_ar,
          ])}
        />
        {state.missing_data?.length ? (
          <div className="mt-4">
            <p className="text-xs font-semibold text-stop">بيانات ناقصة (لم تُقدَّر ولم تُستبدل):</p>
            <p className="mt-1 text-xs text-ink-faint">{state.missing_data.join("، ")}</p>
          </div>
        ) : null}
      </Card>

      <Card
        title="الاستراتيجيات"
        hint={state.strategies.note_ar}
      >
        <Table
          empty="لا استراتيجيات."
          head={["الاستراتيجية", "الحالة", "أنظمة متوافقة", "معتمدة للتنفيذ؟"]}
          rows={state.strategies.strategies.map((s) => [
            `${s.title_ar} (${s.key})`,
            s.state,
            s.compatible_regimes.join("، "),
            s.live_eligible ? "نعم" : "لا",
          ])}
        />
      </Card>
    </div>
  );
}
