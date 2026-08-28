import { apiGet, type AuditResponse } from "@/lib/api";
import { Card, ErrorBox, Pill, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  let data: AuditResponse;
  try {
    data = await apiGet<AuditResponse>("/api/audit?limit=200");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card title="سلامة سلسلة التدقيق">
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone={data.chain_ok ? "ok" : "stop"}>
            {data.chain_ok ? "السلسلة سليمة" : "السلسلة مكسورة"}
          </Pill>
          <span className="text-sm text-ink-soft">عدد الصفوف المفحوصة: {data.checked}</span>
        </div>
        {data.chain_problem_ar ? (
          <p className="mt-3 text-sm text-stop">{data.chain_problem_ar}</p>
        ) : null}
        <p className="mt-3 text-xs text-ink-faint">
          الحماية هنا هي <strong>كشف</strong> التعديل وليس منعه — قاعدة البيانات محلية على جهازك.
          التفاصيل في docs/KNOWN_LIMITATIONS.md.
        </p>
      </Card>

      <Card title="السجل الزمني" hint="يشمل قرارات NO_TRADE تماماً كما يشمل الصفقات.">
        <Table
          head={["#", "الوقت", "الفاعل", "الإجراء", "القرار", "السبب"]}
          empty="السجل فارغ."
          rows={[...data.events].reverse().map((e) => [
            <span key="n" dir="ltr" className="text-xs text-ink-faint">
              {e.sequence}
            </span>,
            <span key="t" className="whitespace-nowrap text-xs">
              {e.at_riyadh}
            </span>,
            <span key="a" dir="ltr" className="text-xs">
              {e.actor}
            </span>,
            <span key="ac" dir="ltr" className="text-xs">
              {e.action}
            </span>,
            <span key="d" dir="ltr" className="text-xs">
              {e.decision}
            </span>,
            <span key="r" className="text-sm text-ink-soft">
              {e.reason_ar}
            </span>,
          ])}
        />
      </Card>
    </div>
  );
}
