import React from 'react';
import { View } from 'react-native';

import { duplicateInstruments, sumOf } from '@/api/positionTotals';
import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  ErrorState,
  Field,
  Hadd,
  LoadingState,
  NavRow,
  Metric,
  Screen,
  Text,
  Trio,
  Vacancy,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentPnlTone, toNumber } from '@/utils/present';

/**
 * المركز الحالي — **عرض فقط**.
 *
 * لا زر إغلاق، ولا تعديل كمية، ولا تحريك وقف أو هدف. الوقف والهدف محفوظان لدى
 * الوسيط لا في التطبيق: لو صمت الهاتف أسبوعاً كاملاً، أو أُلغي هذا الجهاز،
 * تبقى الحماية قائمة كما هي.
 */
export default function PositionScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getCurrentPosition(), {
    previewData: previewOr(fixtures.position),
  });
  /*
    **الحدود نزلت من «اليوم» إلى هنا.**

    سقفُ المراكز وسقفُ أوامر الدخول والخسائرُ المتتالية وحدّا التراجع —
    كلُّها عن المراكز والتعرّض، فموضعُها تبويبُ المحفظة. وكانت تُطيل
    شاشةَ «اليوم» بعشر بطاقاتٍ بعد المراكز، والنموذجُ ينتهي عندها.
  */
  const risk = useEndpoint((c) => c.getRisk(), { previewData: previewOr(fixtures.risk) });
  const r = risk.data;

  if (loading && data === null) {
    return (
      <Screen title={t.position.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.position.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  /**
   * موضع السعر بين الوقف والهدف — «الحدّ» في أصدق مواضعه.
   *
   * المدى يُبنى من الطرفين لا من الاتجاه: في البيع يكون الوقف فوق الهدف،
   * فلو ثُبِّت الوقف بداية المدى لانقلب المقياس. والعتبتان تُلوَّنان بحسب
   * أيّهما الوقف فعلاً، لا بحسب موضعهما على الخط.
   *
   * وأيّ سعرٍ لا يُقرأ رقماً يُلغي العنصر كلّه — لا يُرسم مقياسٌ بطرفٍ مخمَّن.
   */
  const span = ((): {
    now: number; min: number; max: number; stop: number; target: number;
  } | null => {
    const now = toNumber(data.current_price);
    const stop = toNumber(data.stop_price);
    const target = toNumber(data.take_profit_price);
    if (now === null || stop === null || target === null) return null;
    if (stop === target) return null;
    return { now, min: Math.min(stop, target), max: Math.max(stop, target), stop, target };
  })();

  return (
    <Screen
      testID="position-screen"
      title={t.position.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {/*
        **حالةُ المزامنة تُقرأ قبل أي رقم.**

        كانت الشاشة تفرّع على `has_position` وحدها، والخادمُ يُرسل `false`
        سواءٌ لم يجد مركزاً أم لم يستطع أن يقرأ. فيوم 2026-09-04 كان على
        الحساب خمسةُ مراكز والشاشة تقول «لا مركز مفتوح».

        و«لا شيء» و«لم أعرف» لا يُعرضان بصورةٍ واحدة أبداً.
      */}
      {!data.sync.ok ? (
        <Banner
          testID="position-sync-error"
          tone="negative"
          title="تعذّرت قراءة المحفظة"
          body={`${data.sync.error_ar} — هذه ليست «صفر مراكز»، هذه قراءةٌ لم تنجح.`}
        />
      ) : data.sync.stale ? (
        <Banner
          testID="position-sync-stale"
          tone="caution"
          title="قراءةٌ قديمة"
          body={`آخر مزامنة قبل ${data.sync.age_seconds ?? '—'} ثانية. الأرقام قد تكون متأخّرة عن السوق.`}
        />
      ) : null}

      {/*
        **الجهل يُعرَض، لا يُخفى.** حين تفشل القراءة يبقى الدفتر يحمل آخر
        حقيقةٍ معروفة، فتُعرَض موسومةً — لا شاشةٌ فارغة، ولا أرقامٌ تتظاهر
        بأنها الآن. ومركزٌ لم يظهر في قراءةٍ ناجحة يبقى معروضاً أيضاً: غيابٌ
        واحد ليس إغلاقاً.
      */}
      {data.reconciliation === 'RECONNECTING' && data.stale_count > 0 ? (
        <Banner
          testID="position-reconnecting"
          tone="caution"
          title="إعادة اتصال — يُعرَض آخرُ المعروف"
          body={`${data.stale_count} مركزاً من الدفتر، غيرُ مؤكَّدةٍ حتى تنجح قراءةٌ جديدة. ليست «صفر مراكز».`}
        />
      ) : data.reconciliation === 'STALE' && data.stale_count > 0 ? (
        <Banner
          testID="position-stale-rows"
          tone="caution"
          title="مركزٌ غيرُ مؤكَّد"
          body={`${data.stale_count} مركزاً في الدفتر لم يظهر في هذه القراءة — يبقى محسوباً حتى يتأكّد أو يُغلق بتأكيدٍ متكرّر.`}
        />
      ) : null}

      {data.unprotected_count !== null && data.unprotected_count > 0 ? (
        <Banner
          testID="position-unprotected"
          tone="negative"
          title="مركزٌ بلا حماية"
          body={`${data.unprotected_count} مركزاً بلا وقفٍ عند الوسيط — حالةٌ حرجة.`}
        />
      ) : null}

      {/* ----------------------------------------------------------------
          **ثلاثةُ أرقامٍ فوق القائمة — وثالثُها «الحماية».**

          كان المجموع تحت القائمة، وبلا «الحماية» أصلاً: تُقال ببانرٍ يظهر
          عند العطل وحده. وغيابُ الإجابة الموجبة ليس مثلَ حضورها — الصمتُ
          يُقرأ اطمئناناً، و«٤ من ٤ محميّة» تُقرأ معرفة.

          والناقصُ يُعلَن ناقصاً: حقلٌ فارغٌ في مركز يجعل المجموع أقلَّ من
          الحقيقة، ويُقرَأ على أنه الحقيقة.
      ---------------------------------------------------------------- */}
      {data.positions.length > 0
        ? (() => {
            const exposure = sumOf(data.positions, 'notional_display');
            const riskAtStop = sumOf(data.positions, 'risk_at_stop');
            const repeated = duplicateInstruments(data.positions);
            const guarded = data.positions.filter(
              (position) => position.protection_held_by_broker,
            ).length;
            const total = data.positions.length;
            return (
              <>
                <Trio
                  testID="position-trio"
                  tiles={[
                    {
                      label: 'التعرّض',
                      value: exposure.value === null ? '—' : exposure.value.toFixed(2),
                    },
                    { label: 'غير محقَّق', value: data.total_unrealised ?? '—' },
                    {
                      label: t.home.protectedCount,
                      value: `${guarded}/${total}`,
                      tone: guarded === total ? 'positive' : 'negative',
                      spoken: `${guarded} من ${total} محميّة`,
                    },
                  ]}
                />
                <Card testID="position-totals-card" title="المخاطرة المفتوحة">
                  <Field
                    testID="total-exposure"
                    label="التعرّض"
                    value={exposure.value === null ? null : exposure.value.toFixed(2)}
                  />
                  <Field
                    testID="total-risk"
                    label="المخاطرة المفتوحة عند الوقف"
                    value={riskAtStop.value === null ? null : riskAtStop.value.toFixed(2)}
                    tone="caution"
                  />
                  {exposure.missing > 0 || riskAtStop.missing > 0 ? (
                    <Text variant="caption" tone="secondary" testID="total-incomplete">
                      {`مجموعٌ ناقص: ${Math.max(exposure.missing, riskAtStop.missing)} من ${total} مركزاً بلا قيمة. الرقم أقلّ من الحقيقة.`}
                    </Text>
                  ) : null}
                  {repeated.length > 0 ? (
                    <Banner
                      testID="position-duplicate-instrument"
                      tone="negative"
                      title="تكرارُ أداة"
                      body={repeated.map((d) => `${d.instrument}: ${d.count} مراكز`).join(' · ')}
                    />
                  ) : null}
                </Card>
              </>
            );
          })()
        : null}

      {data.open_count !== null && data.open_count >= 1 && data.positions.length > 0 ? (
        <Card testID="position-all-card" title={`المراكز المفتوحة (${data.open_count})`}>
          {data.positions.map((position) => (
            <View key={position.id ?? `${position.instrument}-${position.opened_utc}`}>
              <Field
                label={`${position.instrument_ar ?? position.instrument ?? '—'} · ${
                  position.direction_ar ?? '—'
                } · ${position.size_display ?? '—'}`}
                value={position.unrealised_pnl}
                tone={presentPnlTone(position.unrealised_pnl_sign)}
              />
              <Text variant="caption" tone="secondary" accessibilityRole="text">
                {`دخول ${position.entry_price ?? '—'} · وقف ${
                  position.stop_price ?? '—'
                } · هدف ${position.take_profit_price ?? '—'}${
                  position.protection_held_by_broker ? '' : ' · بلا حماية'
                }${position.reconciliation === 'STALE' ? ' · غيرُ مؤكَّد' : ''}`}
              </Text>
              <Divider />
            </View>
          ))}
          {data.total_unrealised !== null ? (
            <Field label="مجموع غير المحقّق" value={data.total_unrealised} />
          ) : null}

        </Card>
      ) : null}

      {data.has_position === null ? null : !data.has_position ? (
        <Vacancy
          testID="position-empty"
          what={t.position.none}
          why={t.position.noneWhy}
          next={t.position.noneNext}
        />
      ) : data.positions.length > 1 ? null : (
        <>
          <Card testID="position-summary-card" title={data.instrument_ar ?? data.instrument ?? '—'}>
            <View style={{ flexDirection: 'row', gap: theme.spacing.xl }}>
              <Metric
                testID="position-pnl"
                label={t.position.unrealised}
                value={data.unrealised_pnl}
                tone={presentPnlTone(data.unrealised_pnl_sign)}
              />
            </View>
            <Divider />
            <Field label={t.position.direction} value={data.direction_ar} />
            <Field label={t.position.opened} value={formatInstant(data.opened_utc)} />
            <Field label={t.position.strategy} value={data.strategy_ar} />
          </Card>

          <Card testID="position-levels-card" title="المستويات">
            <Field label={t.position.entry} value={data.entry_price} />
            <Field label={t.position.current} value={data.current_price} />
            <Field label={t.position.stop} value={data.stop_price} tone="negative" />
            <Field label={t.position.target} value={data.take_profit_price} tone="positive" />
            <Divider />
            <Field label={t.position.size} value={data.size_display} />
            <Field label={t.position.notional} value={data.notional_display} />
            <Field label={t.position.riskAtStop} value={data.risk_at_stop} tone="caution" />
            {span !== null ? (
              <>
                <Divider />
                <Hadd
                  testID="position-hadd"
                  value={span.now}
                  min={span.min}
                  max={span.max}
                  showFill={false}
                  label={t.position.span}
                  readout={data.current_price ?? '—'}
                  thresholds={[
                    { at: span.stop, tone: 'negative' },
                    { at: span.target, tone: 'positive' },
                  ]}
                  accessibilityLabel={`${t.position.span}. ${t.position.stop} ${
                    data.stop_price ?? '—'
                  }، ${t.position.current} ${data.current_price ?? '—'}، ${
                    t.position.target
                  } ${data.take_profit_price ?? '—'}.`}
                  style={{ marginTop: theme.spacing.xs }}
                />
              </>
            ) : null}
          </Card>

          {data.notes_ar.length > 0 ? (
            <Card testID="position-notes-card" title="ملاحظات">
              {data.notes_ar.map((note, index) => (
                <Text
                  key={`${index}-${note}`}
                  variant="caption"
                  tone="secondary"
                  accessibilityRole="text"
                >
                  {note}
                </Text>
              ))}
            </Card>
          ) : null}
        </>
      )}

      {data.protection_held_by_broker ? (
        <Banner
          testID="protection-banner"
          tone="info"
          title="الحماية لدى الوسيط"
          body={t.position.protection}
        />
      ) : null}

      {/*
        بقيّة شاشات هذا التبويب.

        كانت هذه الشاشات مبنيّة ومسجَّلة في `_layout` ومُختبَرة — **ولا صفَّ
        انتقالٍ واحد يفتحها**. فالتبويبات الأربعة تصل إلى أربع شاشات، والباقي
        لا يُفتَح إلا برابطٍ عميق من إشعار. وهو العطل نفسه المتكرر في هذا
        المشروع بصورة أخرى: شيءٌ بُني ولم يُنفَّذ قط.

        ويحرسه الآن `__tests__/navigation-reach.test.tsx`: كل شاشة تحت
        `(app)` يجب أن يصل إليها تبويبٌ أو صفٌّ من شاشة تبويب.
      */}
      {/* ----------------------------------------------------------------
          **حدودٌ يحملها العقد ولا تُعرض.**

          `RiskData` يحمل سقفَ المراكز وسقفَ أوامر الدخول اليومية والخسائرَ
          المتتالية وحدَّي التراجع — ولم يكن **واحدٌ منها** معروضاً. والعيب
          `C2` — أربعةُ مراكز مقابل سقفٍ ثلاثة — كان سيُرى في اليوم نفسه لو
          عُرض حقلان موجودان في العقد أصلاً. الشاشةُ لا تمنع الخرق، لكنها
          كانت ستكشفه.
      ---------------------------------------------------------------- */}
      {r !== null ? (
        <>
          <Card testID="limits-card" title="الحدود">
            <Field label="الملف" value={r.profile_name_ar} testID="limit-profile-name" />
            <Field
              label="رأس المال المحسوب عليه"
              value={r.equity_used}
              testID="limit-equity-used"
            />
            <Divider />
            <Field
              label="المراكز المفتوحة"
              value={
                r.open_positions === null
                  ? null
                  : `${r.open_positions} من ${r.max_open_positions ?? '—'}`
              }
              testID="limit-open-positions"
              tone={
                r.open_positions !== null &&
                r.max_open_positions !== null &&
                r.open_positions > r.max_open_positions
                  ? 'negative'
                  : undefined
              }
            />
            {r.open_positions !== null &&
            r.max_open_positions !== null &&
            r.open_positions > r.max_open_positions ? (
              <Text variant="caption" tone="secondary" testID="limit-open-positions-breach">
                {`مفتوحٌ فوق السقف بمقدار ${r.open_positions - r.max_open_positions}. لا يُفتَح جديد.`}
              </Text>
            ) : null}
            <Field
              label="أوامر الدخول اليوم"
              value={
                r.entry_orders_today === null
                  ? null
                  : `${r.entry_orders_today} من ${r.max_entry_orders_per_day ?? '—'}`
              }
              testID="limit-entry-orders"
            />
            <Field
              label="خسائر متتالية"
              value={r.consecutive_losses === null ? null : String(r.consecutive_losses)}
              testID="limit-consecutive-losses"
              tone={r.two_loss_lock_active ? 'caution' : undefined}
            />
            <Divider />
            <Field
              label="توقّف التراجع التشغيلي"
              value={r.operational_drawdown_stop}
              testID="limit-operational-drawdown"
            />
            <Field
              label="الحدّ المطلق للخسارة"
              value={r.absolute_loss_boundary}
              testID="limit-absolute-loss"
            />
          </Card>

          <Card testID="risk-week-card" title="الأسبوع">
            <Field label="المستهلَك" value={r.risk_used_week} />
            <Field label="المتبقّي" value={r.risk_remaining_week} />
            <Field
              label="المسافة إلى قاطع الطوارئ"
              value={r.distance_to_kill_switch}
              tone="caution"
            />
          </Card>
        </>
      ) : null}

      <Card testID="position-more-card" title={t.nav.more}>
        <NavRow
          testID="nav-chart"
          label={t.nav.chart}
          hint={t.navHint.chart}
          href="/(app)/chart"
        />
        <NavRow
          testID="nav-management"
          label={t.nav.management}
          hint={t.navHint.management}
          href="/(app)/management"
        />
        <NavRow
          testID="nav-history"
          label={t.nav.history}
          hint={t.navHint.history}
          href="/(app)/history"
        />
        <NavRow
          testID="nav-performance"
          label={t.nav.performance}
          hint={t.navHint.performance}
          href="/(app)/performance"
        />
      </Card>

      <Banner
        testID="position-readonly-banner"
        tone="neutral"
        title={t.common.readOnly}
        body={t.position.cannotModify}
      />
    </Screen>
  );
}
