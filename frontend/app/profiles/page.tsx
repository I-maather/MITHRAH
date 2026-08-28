import { apiGet, type ProfilesState } from "@/lib/api";
import { Card, ErrorBox, Pill, Stat, Table } from "@/components/ui";
import { ProfileSelector } from "./selector";

export const dynamic = "force-dynamic";

export default async function ProfilesPage() {
  let state: ProfilesState;
  try {
    state = await apiGet<ProfilesState>("/api/profiles");
  } catch (error) {
    return <ErrorBox message={error instanceof Error ? error.message : "خطأ"} />;
  }

  const l = state.limits;
  const pendingDiffers = state.pending_profile && state.pending_profile !== state.effective_profile;

  return (
    <div className="flex flex-col gap-5">
      <Card
        title="ملف التداول"
        hint="الملف يغيّر حجم المخاطرة وتواتر الفرص فقط — ولا يخفّف أي متطلب تحليلي أو أمني."
      >
        <div className="mb-5 flex flex-wrap gap-2">
          <Pill>الملف المختار: {state.selected_name_ar}</Pill>
          <Pill tone="ok">الملف الفعّال: {state.effective_name_ar}</Pill>
          {pendingDiffers ? (
            <Pill tone="warn">
              معلّق: {state.pending_profile} — متبقٍ {state.cooling_remaining_ar}
            </Pill>
          ) : null}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="مستوى المخاطرة" value={state.risk_level_ar} />
          <Stat label="الحد لكل صفقة" value={`${l.max_risk_per_trade} $`} />
          <Stat label="الحد اليومي" value={`${l.max_daily_loss} $`} />
          <Stat label="الحد الأسبوعي" value={`${l.max_weekly_loss} $`} />
          <Stat label="الحد التشغيلي للتراجع" value={`${l.operational_drawdown_stop} $`} />
          <Stat label="احتياطي الفجوة" value={`${l.gap_slippage_reserve} $`} />
          <Stat label="الحاجز الإجمالي" value={`${l.absolute_loss_boundary} $`} tone="stop" />
          <Stat
            label="فترة الانتظار قبل رفع المخاطرة"
            value={pendingDiffers ? state.cooling_remaining_ar : "—"}
          />
          <Stat label="أدنى R:R صافٍ" value={l.min_net_reward_risk} />
          <Stat label="أدنى درجة جودة" value={`${l.min_quality_score} / 100`} />
          <Stat label="مراكز مفتوحة" value={String(l.max_open_positions)} />
          <Stat label="دخول يومياً" value={String(l.max_entry_orders_per_day)} />
        </div>

        {state.change_blocked_reason_ar ? (
          <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-stop">
            سبب عدم السماح بتغيير الملف: {state.change_blocked_reason_ar}
          </p>
        ) : null}
      </Card>

      <Card title="اختيار الملف">
        <ProfileSelector
          effective={state.effective_profile}
          pending={state.pending_profile}
          blockedReasonAr={state.change_blocked_reason_ar}
          options={state.available_profiles}
        />
      </Card>

      <Card title="مقارنة الملفات الثلاثة">
        <Table
          empty="لا ملفات."
          head={[
            "الملف",
            "لكل صفقة",
            "يومي",
            "أسبوعي",
            "أدنى R:R",
            "أدنى درجة",
            "خسارة كاملة تُنهي اليوم",
          ]}
          rows={state.available_profiles.map((p) => [
            p.name_ar,
            `${p.limits.max_risk_per_trade} $`,
            `${p.limits.max_daily_loss} $`,
            `${p.limits.max_weekly_loss} $`,
            p.limits.min_net_reward_risk,
            String(p.limits.min_quality_score),
            p.limits.full_risk_loss_ends_day ? "نعم" : "لا",
          ])}
        />
      </Card>

      <Card
        title="دستور الخسارة العام"
        hint={state.global_loss_constitution.note_ar}
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            label="الحد التشغيلي"
            value={`${state.global_loss_constitution.operational_drawdown_stop} $`}
          />
          <Stat
            label="احتياطي الفجوة"
            value={`${state.global_loss_constitution.gap_slippage_reserve} $`}
          />
          <Stat
            label="الحاجز المطلق"
            value={`${state.global_loss_constitution.absolute_loss_boundary} $`}
            tone="stop"
          />
        </div>
        <p className="mt-4 text-xs text-ink-faint">
          الوقف العادي لا يضمن الحاجز عند الفجوة السعرية. الاحتياطي يقلّل الاحتمال ولا يلغيه.
        </p>
      </Card>

      <Card
        title="ما لا يغيّره الملف أبداً"
        hint="هذه القائمة ثابتة في الكود، ولكل بند فيها اختبار."
      >
        <ul className="grid gap-1.5 text-sm text-ink-soft sm:grid-cols-2">
          {state.never_weakened_by_profile.map((item) => (
            <li key={item}>• {item}</li>
          ))}
        </ul>
      </Card>

      <Card
        title="عدّادات لا يُعاد ضبطها بالتبديل"
        hint="تبديل الملف لا يمسّ أياً من هذه القيم — لا صعوداً ولا هبوطاً."
      >
        <Table
          empty="لا عدّادات."
          head={["العدّاد", "القيمة الحالية"]}
          rows={Object.entries(state.counters).map(([k, v]) => [k, String(v)])}
        />
      </Card>
    </div>
  );
}
