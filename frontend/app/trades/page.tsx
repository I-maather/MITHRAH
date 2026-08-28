import { apiGet, type TradesResponse } from "@/lib/api";
import { Card, ErrorBox, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

export default async function TradesPage() {
  let data: TradesResponse;
  try {
    data = await apiGet<TradesResponse>("/api/trades");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      {data.error_ar ? <ErrorBox message={data.error_ar} /> : null}

      <Card title="المراكز المفتوحة">
        <Table
          head={["الأصل", "الكمية", "متوسط التكلفة", "غير المحقق"]}
          empty="لا توجد مراكز مفتوحة."
          rows={data.positions.map((p) => [
            <span key="s" dir="ltr">{cell(p["symbol"])}</span>,
            <span key="q" dir="ltr">{cell(p["quantity"])}</span>,
            <span key="c" dir="ltr">{cell(p["average_cost"])}</span>,
            <span key="u" dir="ltr">{cell(p["unrealized_pnl"])}</span>,
          ])}
        />
      </Card>

      <Card title="الأوامر">
        <Table
          head={["معرّف الوسيط", "الأصل", "النوع", "الكمية", "المنفذ", "متوسط السعر", "الحالة"]}
          empty="لا توجد أوامر."
          rows={data.orders.map((o) => [
            <span key="i" dir="ltr" className="text-xs">{cell(o["broker_order_id"])}</span>,
            <span key="s" dir="ltr">{cell(o["symbol"])}</span>,
            <span key="t" dir="ltr">{cell(o["order_type"])}</span>,
            <span key="q" dir="ltr">{cell(o["quantity"])}</span>,
            <span key="f" dir="ltr">{cell(o["filled_quantity"])}</span>,
            <span key="p" dir="ltr">{cell(o["average_fill_price"])}</span>,
            <span key="st" dir="ltr" className="text-xs">{cell(o["status"])}</span>,
          ])}
        />
      </Card>

      <Card title="التنفيذ الفعلي" hint="السعر والعمولة كما أكّدهما الوسيط، لا كما توقعناهما.">
        <Table
          head={["المعرّف", "الأصل", "الكمية", "السعر", "العمولة", "الوقت"]}
          empty="لا توجد تنفيذات."
          rows={data.executions.map((x) => [
            <span key="i" dir="ltr" className="text-xs">{cell(x["execution_id"])}</span>,
            <span key="s" dir="ltr">{cell(x["symbol"])}</span>,
            <span key="q" dir="ltr">{cell(x["quantity"])}</span>,
            <span key="p" dir="ltr">{cell(x["price"])}</span>,
            <span key="c" dir="ltr">{cell(x["commission"])}</span>,
            <span key="t" dir="ltr" className="text-xs">{cell(x["executed_at_utc"])}</span>,
          ])}
        />
      </Card>
    </div>
  );
}
