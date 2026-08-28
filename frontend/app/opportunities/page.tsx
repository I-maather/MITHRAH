import { apiGet, type Opportunities } from "@/lib/api";
import { Card, ErrorBox, Pill, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function OpportunitiesPage() {
  let data: Opportunities;
  try {
    data = await apiGet<Opportunities>("/api/opportunities");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card
        title="القائمة البيضاء"
        hint="هذه ليست توصيات شراء. كل صف يشرح لماذا الأصل مسموح به وما حالته الآن."
      >
        <Table
          head={["الأصل", "الاسم", "الاستراتيجية", "السبب", "الحالة"]}
          empty="القائمة البيضاء فارغة."
          rows={data.allowlist.map((row) => [
            <span key="s" dir="ltr" className="font-medium">
              {row.symbol}
            </span>,
            row.name_ar,
            <span key="st" dir="ltr" className="text-xs">
              {row.strategy}
            </span>,
            <span key="r" className="text-xs text-ink-soft">
              {row.rationale_ar}
            </span>,
            <Pill key="p" tone="warn">
              {row.status_ar}
            </Pill>,
          ])}
        />
      </Card>

      <Card title="أصول مرفوضة صراحةً" hint="مذكورة هنا حتى لا تُضاف بالخطأ لاحقاً.">
        <Table
          head={["الأصل", "سبب الرفض"]}
          empty="لا يوجد."
          rows={data.denylist.map((row) => [
            <span key="s" dir="ltr" className="font-medium">
              {row.symbol}
            </span>,
            <span key="r" className="text-sm text-ink-soft">
              {row.reason_ar}
            </span>,
          ])}
        />
      </Card>
    </div>
  );
}
