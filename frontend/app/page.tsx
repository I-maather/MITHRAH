import { apiGet, type Today } from "@/lib/api";
import { Card, ErrorBox, Pill, Stat } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  let data: Today;
  try {
    data = await apiGet<Today>("/api/today");
  } catch (error) {
    return (
      <ErrorBox
        message={`تعذر الوصول إلى الخادم. شغّلي الباك-إند أولاً (make run-api). التفاصيل: ${
          error instanceof Error ? error.message : "خطأ غير معروف"
        }`}
      />
    );
  }

  const halted = data.kill_switch.active;

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="label">قرار اليوم</div>
            <p className="mt-1 text-lg font-medium">{data.verdict_ar}</p>
            {data.no_trade_reason_ar ? (
              <p className="mt-2 text-sm text-ink-soft">السبب: {data.no_trade_reason_ar}</p>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill tone={data.trading_allowed ? "ok" : "warn"}>
              {data.trading_allowed ? "التداول مسموح" : "التداول غير مسموح"}
            </Pill>
            <Pill tone={data.live_trading_enabled ? "stop" : "neutral"}>
              {data.live_trading_enabled ? "وضع حقيقي" : "وضع محاكاة / ورقي"}
            </Pill>
            <Pill tone={data.risk_mode === "VALIDATION" ? "neutral" : "warn"}>
              {data.risk_mode}
            </Pill>
            {halted ? <Pill tone="stop">Kill Switch مفعّل</Pill> : null}
          </div>
        </div>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card title="السوق والاتصال">
          <div className="grid grid-cols-2 gap-5">
            <Stat
              label="حالة السوق"
              value={data.market.is_open ? "مفتوح" : "مغلق"}
              tone={data.market.is_open ? "ok" : "warn"}
              sub={data.market.reason_ar}
            />
            <Stat
              label="الوسيط"
              value={data.broker.connected ? "متصل" : "غير متصل"}
              tone={data.broker.connected ? "ok" : "stop"}
              sub={data.broker.name}
            />
            <Stat label="الآن" value={data.now_riyadh} />
            <Stat
              label="إغلاق الجلسة"
              value={data.market.close_riyadh ?? "—"}
              sub="بتوقيت الرياض"
            />
          </div>
        </Card>

        <Card title="الحساب">
          <div className="grid grid-cols-2 gap-5">
            <Stat label="رأس المال المرجعي" value={`$${data.equity.baseline}`} />
            <Stat label="الرصيد الحالي" value={`$${data.equity.current}`} />
            <Stat label="المراكز المفتوحة" value={String(data.open_positions)} />
            <Stat
              label="المسافة إلى Kill Switch"
              value={`$${data.distance_to_kill_switch}`}
              tone={Number(data.distance_to_kill_switch) <= 1 ? "stop" : "ok"}
              sub={`الحد الصارم $${data.limits.total}`}
            />
          </div>
        </Card>
      </div>

      <Card title="استهلاك حدود الخسارة" hint="الأرقام تشمل العمولات والسبريد والانزلاق المتوقع.">
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <Stat
            label="خسارة اليوم"
            value={`$${data.losses.today} / $${data.limits.daily}`}
            tone={Number(data.losses.today) > 0 ? "warn" : "neutral"}
          />
          <Stat
            label="خسارة الأسبوع"
            value={`$${data.losses.week} / $${data.limits.weekly}`}
            tone={Number(data.losses.week) > 0 ? "warn" : "neutral"}
          />
          <Stat
            label="الخسارة الإجمالية"
            value={`$${data.losses.total} / $${data.limits.total}`}
            tone={Number(data.losses.total) > 0 ? "stop" : "neutral"}
          />
        </div>
        <p className="mt-4 text-xs text-ink-faint">
          المخاطرة المستهدفة للصفقة ${data.limits.target_risk_per_trade} والحد الأقصى المطلق $
          {data.limits.max_risk_per_trade}. وضع المخاطرة الحالي: {data.risk_mode} —{" "}
          {data.risk_mode_purpose_ar}
        </p>
      </Card>

      {halted ? (
        <Card title="سبب التوقف">
          <p className="text-sm">{data.kill_switch.reason_ar}</p>
          <p className="mt-2 text-xs text-ink-faint">
            المُطلِق: {data.kill_switch.trigger} — {data.kill_switch.at_riyadh}
          </p>
        </Card>
      ) : null}
    </div>
  );
}
