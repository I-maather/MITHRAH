import { apiGet, type BrokerState, type CfdPreview } from "@/lib/api";
import { Card, ErrorBox, Pill, Stat, Table } from "@/components/ui";
import { PausePanel } from "./pause-panel";

export const dynamic = "force-dynamic";

const STOP_DISTANCES = [25, 50, 75] as const;

export default async function BrokerPage() {
  let state: BrokerState;
  let previews: CfdPreview[];
  try {
    state = await apiGet<BrokerState>("/api/broker");
    previews = await Promise.all(
      STOP_DISTANCES.map((pips) =>
        apiGet<CfdPreview>(`/api/cfd-preview?stop_pips=${pips}&take_profit_pips=${pips * 2}`),
      ),
    );
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  const first = previews[0];

  return (
    <div className="flex flex-col gap-5">
      <Card title="الوسيط والبيئة">
        <div className="mb-5 flex flex-wrap gap-2">
          <Pill tone={state.is_demo ? "warn" : "stop"}>
            {state.is_demo ? "بيئة تجريبية — DEMO" : "بيئة حقيقية"}
          </Pill>
          <Pill>{state.broker}</Pill>
          <Pill tone={state.connected ? "ok" : "stop"}>
            {state.connected ? "متصل" : "غير متصل"}
          </Pill>
          <Pill tone={state.live_api_enabled_in_source ? "stop" : "ok"}>
            {state.live_api_enabled_in_source
              ? "واجهة Live مفتوحة في الكود"
              : "واجهة Live مقفلة في الكود"}
          </Pill>
          <Pill tone={state.execution_lock.unlocked ? "stop" : "ok"}>
            {state.execution_lock.unlocked ? "قفل التنفيذ مفتوح" : "قفل التنفيذ مغلق"}
          </Pill>
          <Pill tone={state.local_trading_paused ? "warn" : "neutral"}>
            {state.local_trading_paused ? "الإيقاف المحلي مفعّل" : "الإيقاف المحلي مرفوع"}
          </Pill>
          {state.kill_switch.active ? <Pill tone="stop">Kill Switch مفعّل</Pill> : null}
          <Pill tone={state.risk_mode === "LOCKED_REVIEW" ? "stop" : "neutral"}>
            {state.risk_mode}
          </Pill>
        </div>

        <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
          <Stat label="المحوّل" value={state.adapter_name} />
          <Stat label="الحساب المحدد" value={state.account_masked ?? "لم يُحدَّد بعد"} />
          <Stat label="إصدار دستور المخاطر" value={state.risk_constitution_version} />
          <Stat label="أدوات التنفيذ" value={state.execution_allowlist.join(" · ")} />
        </div>

        <p className="mt-5 text-xs text-ink-faint" dir="ltr">
          {state.base_url}
        </p>
      </Card>

      <Card
        title="الاعتمادات"
        hint="تُعرض حالة الوجود فقط. لا تُعرض أي قيمة، ولا حتى مقنّعة جزئياً."
      >
        <Table
          head={["السرّ", "الحالة", "المصدر"]}
          empty="—"
          rows={state.credentials.map((c) => [
            <span key="n" dir="ltr" className="text-xs">
              {c.name}
            </span>,
            <Pill key="p" tone={c.present ? "ok" : "warn"}>
              {c.present ? "موجود" : "غير مضبوط"}
            </Pill>,
            <span key="s" className="text-xs text-ink-faint">
              {c.source}
            </span>,
          ])}
        />
        <p className="mt-4 text-xs text-ink-faint">
          الضبط يتم من جهازك فقط عبر{" "}
          <code dir="ltr">scripts/configure_capital_credentials.sh</code> — ولا يمر عبر هذه
          الواجهة ولا عبر المحادثة.
        </p>
      </Card>

      <PausePanel paused={state.local_trading_paused} killSwitchActive={state.kill_switch.active} />

      <Card
        title="بطاقة معاينة الصفقة — EUR/USD"
        hint="ثلاث قيم مختلفة لا يجوز الخلط بينها: التعرّض، الهامش المحجوز، والخسارة النقدية."
      >
        {first?.provisional ? (
          <p className="mb-4 rounded-xl bg-amber-50 px-4 py-3 text-sm text-warn">
            {first.provisional_note_ar}
          </p>
        ) : null}

        <Table
          head={[
            "مسافة الوقف",
            "الكمية (وحدات الوسيط)",
            "قيمة التعرّض",
            "الهامش المتوقع",
            "قيمة النقطة",
            "تكلفة السبريد",
            "رسوم الوقف المضمون",
            "احتياطي الانزلاق",
            "الخسارة الكلية",
            "العائد الصافي",
            "R:R الصافي",
            "ضمن 0.75",
          ]}
          empty="—"
          rows={previews.map((preview) => [
            <span key="s" dir="ltr">
              {preview.display.stop_distance_pips} نقطة
            </span>,
            <span key="q" dir="ltr">
              {preview.display.size_broker_units}
            </span>,
            <span key="n" dir="ltr">
              ${preview.display.notional_exposure}
            </span>,
            <span key="m" dir="ltr">
              ${preview.display.margin_required}
            </span>,
            <span key="p" dir="ltr">
              ${preview.display.pip_value}
            </span>,
            <span key="sp" dir="ltr">
              ${preview.display.spread_cost}
            </span>,
            <span key="g" dir="ltr">
              ${preview.display.guaranteed_stop_premium}
            </span>,
            <span key="sl" dir="ltr">
              ${preview.display.slippage_reserve}
            </span>,
            <strong key="r" dir="ltr">
              ${preview.display.all_in_risk_at_stop}
            </strong>,
            <span key="nr" dir="ltr">
              ${preview.display.net_reward}
            </span>,
            <span key="rr" dir="ltr">
              {preview.display.net_reward_risk_ratio}
            </span>,
            <Pill key="c" tone={preview.caps.within_absolute ? "ok" : "stop"}>
              {preview.caps.within_absolute ? "نعم" : "لا"}
            </Pill>,
          ])}
        />

        <div className="mt-5 grid gap-3 border-t border-line pt-4 text-xs text-ink-soft md:grid-cols-3">
          <div>
            <span className="label block">نوع الوقف</span>
            {first?.display.stop_kind === "GUARANTEED" ? "مضمون" : "عادي"}
          </div>
          <div>
            <span className="label block">حركة التعادل</span>
            <span dir="ltr">{first?.display.breakeven_move_pips} نقطة</span>
          </div>
          <div>
            <span className="label block">حالة الإرسال</span>
            {first?.execution_locked ? "لم يُرسل شيء — قفل التنفيذ مغلق" : "قفل التنفيذ مفتوح"}
          </div>
        </div>

        {first?.warnings_ar.length ? (
          <ul className="mt-4 list-inside list-disc space-y-1 text-xs text-ink-faint">
            {first.warnings_ar.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </Card>

      <Card title="إيقاف المفتاح من داخل Capital.com" hint="أقوى من أي زر هنا.">
        <ol className="list-inside list-decimal space-y-2 text-sm text-ink-soft">
          {state.api_key_pause_instructions_ar.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      </Card>

      <Card title="قوائم الأدوات">
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <div className="label mb-2">أدوات الاكتشاف (قراءة فقط)</div>
            <div className="flex flex-wrap gap-2">
              {state.discovery_allowlist.map((epic) => (
                <Pill key={epic}>{epic}</Pill>
              ))}
            </div>
          </div>
          <div>
            <div className="label mb-2">أدوات التنفيذ</div>
            <div className="flex flex-wrap gap-2">
              {state.execution_allowlist.map((epic) => (
                <Pill key={epic} tone="warn">
                  {epic}
                </Pill>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
