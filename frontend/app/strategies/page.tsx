import { apiGet, type StrategiesResponse } from "@/lib/api";
import { Card, ErrorBox, Pill } from "@/components/ui";

export const dynamic = "force-dynamic";

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="label mb-2">{title}</h3>
      <ul className="list-inside list-disc space-y-1 text-sm text-ink-soft">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export default async function StrategiesPage() {
  let data: StrategiesResponse;
  try {
    data = await apiGet<StrategiesResponse>("/api/strategies");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <p className="text-sm">
          الاستراتيجيات المعتمدة والفعّالة الآن: <strong>{data.active_count}</strong>
        </p>
        {data.active_count === 0 ? (
          <p className="mt-2 text-sm text-ink-soft">
            لا توجد استراتيجية معتمدة، لذلك النظام لن يُنتج أي أمر. الاعتماد يتطلب Backtest و
            Walk-forward وموافقة مكتوبة — انظري docs/STRATEGY_APPROVAL.md.
          </p>
        ) : null}
      </Card>

      {data.strategies.map((s) => (
        <Card key={`${s.name}@${s.version}`} title={`${s.name} — الإصدار ${s.version}`}>
          <div className="mb-4 flex flex-wrap gap-2">
            <Pill tone={s.state === "APPROVED" ? "ok" : "warn"}>{s.state}</Pill>
            <Pill>{s.timeframe}</Pill>
            {s.markets.map((m) => (
              <Pill key={m}>{m}</Pill>
            ))}
          </div>
          <p className="mb-5 text-sm">{s.hypothesis_ar}</p>
          <div className="grid gap-5 md:grid-cols-2">
            <List title="شروط الدخول" items={s.entry_conditions_ar} />
            <List title="شروط الخروج" items={s.exit_conditions_ar} />
            <List title="حالات الإبطال" items={s.invalidations_ar} />
            <List title="حالات لا تداول" items={s.no_trade_conditions_ar} />
          </div>
          <div className="mt-5 grid gap-3 border-t border-line pt-4 text-sm md:grid-cols-2">
            <div>
              <span className="label block">التكاليف المفترضة</span>
              {s.assumed_costs_ar}
            </div>
            <div>
              <span className="label block">أدلة Backtest</span>
              {s.backtest_evidence_ar}
            </div>
            <div>
              <span className="label block">أدلة Walk-forward</span>
              {s.walkforward_evidence_ar}
            </div>
            <div>
              <span className="label block">سجل التغييرات</span>
              {s.changelog_ar.join(" · ")}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
