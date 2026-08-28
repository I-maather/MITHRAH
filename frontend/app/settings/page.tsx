import { apiGet, type SettingsResponse } from "@/lib/api";
import { Card, ErrorBox, Pill, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let data: SettingsResponse;
  try {
    data = await apiGet<SettingsResponse>("/api/settings");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card title="وضع التشغيل">
        <div className="flex flex-wrap gap-2">
          <Pill tone={data.live_trading ? "stop" : "ok"}>{data.mode}</Pill>
          <Pill>{data.broker_mode}</Pill>
          <Pill tone={data.risk_mode === "VALIDATION" ? "neutral" : "warn"}>
            {data.risk_mode}
          </Pill>
          <Pill>{data.display_timezone}</Pill>
        </div>
        <p className="mt-4 text-sm text-ink-soft">
          رأس المال المرجعي: <span dir="ltr">${data.baseline_equity_usd}</span>
        </p>
        <p className="mt-2 text-xs text-ink-faint">
          تفعيل التداول الحقيقي لا يتم من هنا. يتطلب متغير بيئة منفصل + ملف موافقة موقّع زمنياً +
          خطوات docs/LIVE_ACTIVATION_CHECKLIST.md.
        </p>
      </Card>

      <Card title="دستور المخاطر">
        <Pill tone={data.risk_constitution_editable ? "stop" : "ok"}>
          {data.risk_constitution_editable ? "قابل للتعديل — خطر" : "غير قابل للتعديل من الواجهة"}
        </Pill>
      </Card>

      <Card title="القائمة البيضاء">
        <Table
          head={["الأصل"]}
          empty="فارغة."
          rows={data.allowlist.map((s) => [
            <span key={s} dir="ltr">
              {s}
            </span>,
          ])}
        />
      </Card>

      <Card title="تقويم حظر الأخبار" hint="الأيام غير المؤكدة تُنتج NO_TRADE تلقائياً.">
        <Table
          head={["اليوم المؤكد"]}
          empty="لا يوجد يوم مؤكد — النظام سيرفض التداول."
          rows={data.blackout_days_confirmed.map((d) => [
            <span key={d} dir="ltr">
              {d}
            </span>,
          ])}
        />
      </Card>
    </div>
  );
}
