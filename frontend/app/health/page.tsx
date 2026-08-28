import { apiGet, type Health } from "@/lib/api";
import { Card, ErrorBox, Pill } from "@/components/ui";

export const dynamic = "force-dynamic";

function Row({ label, ok, note }: { label: string; ok: boolean; note?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 py-3 last:border-0">
      <div>
        <div className="text-sm">{label}</div>
        {note ? <div className="text-xs text-ink-faint">{note}</div> : null}
      </div>
      <Pill tone={ok ? "ok" : "stop"}>{ok ? "سليم" : "مشكلة"}</Pill>
    </div>
  );
}

export default async function HealthPage() {
  let data: Health;
  try {
    data = await apiGet<Health>("/api/health");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card title="مكوّنات النظام" hint={`آخر فحص: ${data.checked_at_riyadh}`}>
        <Row label="الاتصال بالوسيط" ok={data.broker_connected} note={data.broker_name} />
        <Row label="بيانات السوق" ok={data.market_data_ok} />
        <Row label="قاعدة البيانات" ok={data.database_ok} />
        <Row label="المجدول" ok={data.scheduler_ok} />
        <Row label="الساعة والمناطق الزمنية" ok={data.clock_ok} />
        <Row label="سلسلة سجل التدقيق" ok={data.audit_chain_ok} />
        <Row
          label="Kill Switch"
          ok={!data.kill_switch_active}
          note={data.kill_switch_active ? "مفعّل — لا دخول جديد" : "غير مفعّل"}
        />
      </Card>

      <Card title="تفاصيل">
        <ul className="space-y-2 text-sm text-ink-soft">
          {data.details_ar.map((d) => (
            <li key={d}>• {d}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
