import { apiGet, type RiskResponse } from "@/lib/api";
import { Card, ErrorBox, Table } from "@/components/ui";
import { KillSwitchPanel } from "./kill-switch-panel";

export const dynamic = "force-dynamic";

const LABELS: Record<string, string> = {
  mode: "وضع المخاطرة",
  baseline_equity: "رأس المال المرجعي",
  hard_total_loss: "الحد الإجمالي الصارم",
  daily_loss: "الحد اليومي",
  weekly_loss: "الحد الأسبوعي",
  target_risk_per_trade: "المخاطرة المستهدفة للصفقة",
  max_risk_per_trade: "الحد الأقصى المطلق للصفقة",
  max_open_positions: "أقصى مراكز مفتوحة",
  max_entry_orders_per_day: "أقصى أوامر دخول يومياً",
  consecutive_losses_pause: "خسائر متتالية ⇒ توقف",
  consecutive_losses_kill: "خسائر متتالية ⇒ Kill Switch",
  min_reward_risk_ratio: "أدنى نسبة عائد/مخاطرة",
  pause_scope: "نطاق التوقف بعد الخسائر المتتالية",
  enforce_economic_viability: "الحواجز الاقتصادية مفعّلة",
  max_cost_ratio_of_risk: "أقصى نسبة احتكاك من المخاطرة",
  max_breakeven_move_pct: "أقصى حركة مطلوبة للتعادل",
  max_lifetime_entry_orders: "أقصى أوامر دخول في عمر الوضع",
  min_notional_usd: "أدنى قيمة أمر",
  max_notional_usd: "أقصى قيمة أمر",
  requires_per_order_approval: "يتطلب موافقة على كل أمر",
};

export default async function RiskPage() {
  let data: RiskResponse;
  try {
    data = await apiGet<RiskResponse>("/api/risk");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card title="وضع المخاطرة الحالي" hint="التبديل بين الأوضاع لا يتم من الواجهة.">
        <div className="flex flex-wrap items-center gap-2">
          <span className="pill bg-surface-sunken text-ink-soft" dir="ltr">
            {data.risk_mode}
          </span>
          <span
            className={`pill ${
              data.economic_guards_enforced ? "bg-green-50 text-ok" : "bg-amber-50 text-warn"
            }`}
          >
            {data.economic_guards_enforced
              ? "الحواجز الاقتصادية مفعّلة"
              : "الحواجز الاقتصادية معطّلة (وضع تشغيل تجريبي)"}
          </span>
        </div>
        <p className="mt-3 text-sm text-ink-soft">{data.risk_mode_purpose_ar}</p>
        <div className="mt-5">
          <Table
            head={["الوضع", "أقصى مخاطرة/صفقة", "يومي", "أسبوعي", "إجمالي", "الغرض"]}
            empty="—"
            rows={Object.entries(data.modes).map(([name, m]) => [
              <span key="n" dir="ltr" className="font-medium">
                {name}
              </span>,
              <span key="r" dir="ltr">{m.max_risk_pct}%</span>,
              <span key="d" dir="ltr">{m.daily_loss_pct}%</span>,
              <span key="w" dir="ltr">{m.weekly_loss_pct}%</span>,
              <span key="t" dir="ltr">{m.hard_total_loss_pct}%</span>,
              <span key="p" className="text-xs text-ink-soft">{m.purpose_ar}</span>,
            ])}
          />
        </div>
      </Card>

      <Card
        title="دستور المخاطر"
        hint="غير قابل للتعديل من الواجهة. تغييره يتطلب تعديل الكود ومراجعة وإعادة تشغيل."
      >
        <Table
          head={["الحد", "القيمة"]}
          empty="—"
          rows={Object.entries(data.limits).map(([key, value]) => [
            LABELS[key] ?? key,
            <span key={key} dir="ltr" className="tabular-nums">
              {value}
            </span>,
          ])}
        />
        <p className="mt-4 text-xs text-ink-faint" dir="ltr">
          fingerprint: {data.constitution_fingerprint.slice(0, 24)}…
        </p>
      </Card>

      <Card title="الاستخدام الحالي">
        <Table
          head={["البند", "القيمة"]}
          empty="—"
          rows={Object.entries(data.usage).map(([key, value]) => [
            key,
            <span key={key} dir="ltr" className="tabular-nums">
              {String(value)}
            </span>,
          ])}
        />
      </Card>

      <KillSwitchPanel />

      <Card title="سجل تفعيل Kill Switch">
        <Table
          head={["الوقت", "المُطلِق", "السبب", "سياسة الطوارئ"]}
          empty="لم يُفعَّل Kill Switch من قبل."
          rows={data.history.map((h) => [
            h.at_riyadh,
            <span key="t" dir="ltr" className="text-xs">
              {h.trigger}
            </span>,
            h.reason_ar,
            <span key="p" dir="ltr" className="text-xs">
              {h.policy}
            </span>,
          ])}
        />
      </Card>

      <Card title="كل مُطلِقات Kill Switch المُبرمَجة">
        <ul className="grid gap-2 text-sm text-ink-soft sm:grid-cols-2">
          {data.triggers.map((t) => (
            <li key={t.code} className="flex items-baseline gap-2">
              <span dir="ltr" className="text-xs text-ink-faint">
                {t.code}
              </span>
              <span>{t.label_ar}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
