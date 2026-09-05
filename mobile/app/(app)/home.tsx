import React, { useCallback } from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import { ApiError } from '@/api/client';
import {
  AgentCard,
  AnimatedNumber,
  Banner,
  CandleChart,
  Card,
  DayPath,
  Divider,
  ErrorState,
  Field,
  Hadd,
  LoadingState,
  Metric,
  NavRow,
  OfflineBanner,
  RiskMeter,
  Screen,
  StaleBanner,
  SectionTitle,
  StatusPill,
  Text,
  Welcome,
  Vacancy,
  prepareChart,
  spanLabel,
  type ChartLevel,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatCooling, formatInstant, formatRatio, formatSince, formatToday, t } from '@/i18n';
import { useTheme } from '@/theme';
import { dayVerdict } from '@/utils/verdict';
import {
  presentCompleteness,
  presentConnection,
  presentDecision,
  presentMarket,
  presentPnlTone,
  presentSystemPhase,
} from '@/utils/present';

/**
 * لوحة الرئيسية.
 *
 * ## لماذا أُعيد ترتيبها
 *
 * كانت **تسع بطاقات متساوية الوزن** فوق بعضها، فلا شيء فيها أهمّ من شيء —
 * والشاشة التي كل شيء فيها مهمّ لا شيء فيها مهمّ. وقياس 69 لقطة من 18 تطبيقاً
 * وجد أن **لا واحد منها يعرض «لماذا لم أتداول»**. فهذا هو الفراغ، وهذا موضعه:
 * أول ما تقع عليه العين، بحجم العنوان لا بحجم الحاشية.
 *
 * الترتيب الآن يجيب أسئلة بترتيب طرحها:
 *   1. ماذا قرّرتَ اليوم، ولماذا؟   ← الحكم، بحجم العنوان
 *   2. كم بقي لي؟                  ← المتبقّي رقماً كبيراً متحرّكاً
 *   3. هل النظام بخير؟             ← شريط حالة مضغوط
 *   4. التفاصيل                    ← تحت، لمن أرادها
 *
 * وبطاقة «الشاشات» حُذفت: كانت قائمة تنقّل مرسومة كبطاقة، وحلّ محلّها شريط
 * التبويبات أسفل الشاشة.
 *
 * كل قيمة معروضة تأتي من الخادم. ما لم يصل يُقال «غير متاح» ولا يُخترع.
 */
export default function HomeScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();

  const status = useEndpoint((c) => c.getStatus(), { previewData: previewOr(fixtures.status) });
  const decision = useEndpoint((c) => c.getDecision(), {
    previewData: previewOr(fixtures.decision),
  });
  const risk = useEndpoint((c) => c.getRisk(), { previewData: previewOr(fixtures.risk) });
  // **مسار اليوم.** كان محسوباً في الخادم ولا يصل إلى أيّ شاشة.
  const participation = useEndpoint((c) => c.getParticipation(), {
    previewData: previewOr(fixtures.participation),
  });
  const profiles = useEndpoint((c) => c.getProfiles(), {
    previewData: previewOr(fixtures.profiles),
  });
  const position = useEndpoint((c) => c.getCurrentPosition(), {
    previewData: previewOr(fixtures.position),
  });
  /**
   * الشموع في الرئيسية.
   *
   * قالت المالكة: «الشموع والمستويات المفروض يكونوا في الرئيسية». ولها حقّ:
   * الحكم يقول «لم أتداول»، والسؤال الذي يليه فوراً «على أيّ سعرٍ حكمتَ؟» —
   * وكان جوابُه شاشةً خلف لمستين.
   */
  const candles = useEndpoint((c) => c.getCandles(), {
    previewData: previewOr(fixtures.candles),
  });

  const refreshAll = useCallback(() => {
    status.refresh();
    decision.refresh();
    risk.refresh();
    profiles.refresh();
    position.refresh();
    candles.refresh();
  }, [status, decision, risk, profiles, position, candles]);

  const offline =
    status.error instanceof ApiError && status.error.kind === 'OFFLINE';
  const anyLoading = status.loading && status.data === null;

  const s = status.data;
  const d = decision.data;
  const r = risk.data;
  const p = profiles.data;
  const pos = position.data;

  /**
   * ما يُرسَم في الرئيسية — أداةً واحدة، وإطاراً واحداً، وبلا منتقيات.
   *
   * الرئيسية ليست شاشة تصفّح: منتقي أربع أدواتٍ وخمسة أطرٍ فيها يجعلها شاشة
   * الشموع مكرّرة، ويوحي بأن النظام يقرّر على أيّها اختير. فالمعروض هنا **ما
   * يعني المالكة الآن**: أداة مركزها إن كان لها مركز، وإلا أول رمزٍ رتّبه
   * الخادم — على الإطار الذي يُقاس عليه القرار وحده. وما عداه خلف صفّ الانتقال.
   *
   * وكل حقلٍ يُقرأ دفاعياً: العقد يعد بها والاستجابة قد تنقص، ولوحةٌ تنهار على
   * حقلٍ ناقص أسوأ من لوحةٍ بلا رسم. (حرسه `sparse-data.test.tsx`، وسقط فيه
   * هذا الرسم أوّل يوم.)
   */
  const home = ((): {
    symbol: string;
    resolution: string;
    prepared: NonNullable<ReturnType<typeof prepareChart>>;
    levels: ChartLevel[];
  } | null => {
    const cd = candles.data;
    if (cd === null) {
      return null;
    }
    const symbols = cd.symbols ?? [];
    const owner = cd.levels?.symbol ?? null;
    const symbol = owner !== null && symbols.includes(owner) ? owner : (symbols[0] ?? null);
    if (symbol === null) {
      return null;
    }
    const perFrame = cd.instruments?.[symbol] ?? {};
    const available = (cd.resolutions ?? []).filter((r) => Array.isArray(perFrame[r]));
    const resolution = available.includes(cd.decision_resolution)
      ? cd.decision_resolution
      : (available[0] ?? null);
    if (resolution === null) {
      return null;
    }
    /** المستويات لأداة المركز وحدها — ورسمُها على أداةٍ أخرى كذبةٌ في المعنى. */
    const levels: ChartLevel[] =
      owner === symbol
        ? ([
            { key: 'entry' as const, label: t.chart.entry, raw: cd.levels?.entry ?? null, color: theme.colors.textPrimary },
            { key: 'stop' as const, label: t.chart.stop, raw: cd.levels?.stop ?? null, color: theme.colors.negative },
            { key: 'target' as const, label: t.chart.target, raw: cd.levels?.target ?? null, color: theme.colors.positive },
          ]
            .map((row) => ({ ...row, value: Number(row.raw) }))
            .filter((row) => row.raw !== null && Number.isFinite(row.value))
            .map(({ key, label, value, color }) => ({ key, label, value, color })) as ChartLevel[])
        : [];
    const prepared = prepareChart(perFrame[resolution] ?? [], levels);
    return prepared === null ? null : { symbol, resolution, prepared, levels };
  })();

  /** المتبقّي رقماً — للعدّ المتدرّج. نصٌّ غير قابل للتحويل ⇒ `null` بلا تخمين. */
  const remainingToday = ((): number | null => {
    const v = Number(r?.risk_remaining_today?.replace(/,/g, ''));
    return Number.isFinite(v) ? v : null;
  })();

  /** الربح غير المحقّق رقماً. نصٌّ غير قابل للتحويل ⇒ يُعرض كما هو بلا حركة. */
  const unrealised = ((): number | null => {
    const v = Number(pos?.unrealised_pnl?.replace(/[,\s+]/g, '').replace('−', '-'));
    return Number.isFinite(v) ? v : null;
  })();

  /** حدّ اليوم = المستهلَك + المتبقّي. لا حقل له في العقد، فيُشتقّ لا يُخترع. */
  const limitToday = ((): string | null => {
    const used = Number(r?.risk_used_today?.replace(/,/g, ''));
    const remaining = Number(r?.risk_remaining_today?.replace(/,/g, ''));
    if (!Number.isFinite(used) || !Number.isFinite(remaining)) {
      return null;
    }
    return (used + remaining).toFixed(2);
  })();

  const riskRatio = ((): number | null => {
    if (r === null) {
      return null;
    }
    const used = Number(r.risk_used_today?.replace(/,/g, ''));
    const remaining = Number(r.risk_remaining_today?.replace(/,/g, ''));
    if (!Number.isFinite(used) || !Number.isFinite(remaining)) {
      return null;
    }
    const total = used + remaining;
    return total > 0 ? used / total : null;
  })();

  // **الجهل يُعلن جهلاً.** `unknown` تجمع ثلاثة: انقطاعٌ، أو بياناتٌ
  // قديمة، أو محفظةٌ لم تُقرأ. وأيٌّ منها يجعل «لا شيء يحتاجكِ» كذبةً.
  const verdict = dayVerdict({
    // `kill_switch` نفسها قد تغيب في حمولةٍ ناقصة — لا حقلُها وحده.
    killSwitchActive: s?.kill_switch?.active ?? false,
    unknown: offline || status.stale || pos === null,
    locallyPaused: s?.locally_paused ?? false,
    openPositions: pos?.open_count ?? null,
  });

  return (
    <Screen
      root
      testID="home-screen"
      // العنوان يملكه شريط التبويبات وحده. كان يُكتب ثلاث مرّات في شاشة
      // واحدة: هيدر التنقّل، وعنوان الشاشة، والتبويب.
      title={formatToday()}
      subtitle={t.app.tagline}
      preview={preview}
      onRefresh={refreshAll}
      refreshing={status.loading}
    >
      {offline ? <OfflineBanner /> : null}
      {!offline && status.stale ? (
        <StaleBanner sinceLabel={formatSince(s?.last_refresh_utc ?? null)} />
      ) : null}

      {anyLoading ? <LoadingState /> : null}

      {status.error !== null && s === null ? (
        <ErrorState error={status.error} onRetry={refreshAll} />
      ) : null}

      {/* ----------------------------------------------------------------
          **الحكم قبل الرقم.**

          كان هنا كلمةٌ واحدة («لم أتداول») تعلوها كلمةٌ أصغر («اليوم»).
          وسؤال المالكة الفعليّ «هل أتدخّل؟» لا يُجاب بكلمة: «لا شيء يحتاجكِ
          اليوم.» جوابٌ، و«لم أتداول» تقريرُ حالة.

          والجملة تُشتقّ من الحالة في `utils/verdict.ts` — والجهلُ فيها يعلو
          الصمت، فشاشةٌ تقول «لا شيء يحتاجكِ» والاتصال منقطعٌ تكذب.
      ---------------------------------------------------------------- */}
      {s !== null || d !== null ? (
        <View style={{ gap: theme.spacing.sm, paddingBottom: theme.spacing.xs }}>
          <Welcome
            testID="home-verdict"
            greeting={verdict.greeting}
            verdict={verdict.verdict}
          />
          {s !== null && s.no_trade_reason_ar !== null ? (
            <Text variant="body" tone="secondary" testID="no-trade-reason">
              {s.no_trade_reason_ar}
            </Text>
          ) : d !== null && d.explanation_ar !== null ? (
            <Text variant="body" tone="secondary" testID="decision-explanation">
              {d.explanation_ar}
            </Text>
          ) : null}
          {d?.blocking_reasons_ar.map((reason, index) => (
            <View
              key={`${index}-${reason}`}
              style={{ flexDirection: 'row', gap: theme.spacing.sm }}
              accessible
              accessibilityRole="text"
              accessibilityLabel={reason}
            >
              <Text variant="caption" tone="tertiary">
                ·
              </Text>
              <Text variant="caption" tone="secondary" style={{ flex: 1 }}>
                {reason}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* ---- الشموع والمستويات: على أيّ سعرٍ كان هذا الحكم ---- */}
      {home !== null ? (
        <Card
          testID="home-chart-card"
          title={`${home.symbol} · ${t.chart.frames[home.resolution] ?? home.resolution}`}
        >
          <CandleChart testID="home-chart" prepared={home.prepared} height={188} />
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text variant="micro" tone="tertiary" testID="home-chart-span">
              {spanLabel(home.prepared.bars)}
            </Text>
            <Text variant="micro" tone="tertiary">
              {home.levels.length === 0 ? t.chart.noPosition : t.chart.levelsOn}
            </Text>
          </View>
          <NavRow testID="nav-chart" label={t.nav.chart} hint={t.navHint.chart} href="/(app)/chart" />
        </Card>
      ) : null}

      {/* ---- المحفظة: المال قبل الحدود ---- */}
      {r !== null ? (
        <Card testID="portfolio-card" title={t.home.portfolio}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.xl }}>
            <Metric
              testID="portfolio-broker"
              label={t.home.brokerEquity}
              value={r.portfolio?.broker_equity ?? null}
              /*
                السبب **يُقرأ من الخادم** ولا يُفترض هنا.

                كانت هذه التسمية مثبَّتة: «لم يُقرَأ — الوسيط غير متصل».
                فعُرضت على المالكة بينما شاشة النظام تقول في اللحظة نفسها
                إن الوسيط **متصل** — والسبب الحقيقي كان `AttributeError`
                على ميثود لا وجود لها. شاشتان تتناقضان، وإحداهما تخمّن.
              */
              caption={
                (r.portfolio?.broker_equity ?? null) === null
                  ? (r.portfolio?.note_ar ?? t.home.brokerEquityMissing)
                  : undefined
              }
            />
            <Metric
              testID="portfolio-baseline"
              label={t.home.baselineEquity}
              value={r.portfolio?.baseline_equity ?? null}
              caption={t.home.baselineEquityHint}
            />
          </View>
          {/*
            الخلاف يُعرض لأنه **معلومة لا خطأ**: كل الحدود تُحسب من المرجعي،
            فاختلافه عن الرصيد الفعلي يعني أن حدودك محسوبة على رقم غير واقعي.
            وقد بقي هذا صامتاً حتى انكشف بالمصادفة: ١٥٠ مرجعاً و١٤٠ في الحساب.
          */}
          {r.portfolio?.diverged ? (
            <Banner
              testID="baseline-drift-banner"
              tone="caution"
              title={t.home.baselineDrift}
              body={r.portfolio?.note_ar ?? undefined}
            />
          ) : null}
        </Card>
      ) : null}

      {/* ---- كم بقي لي ---- */}
      {r !== null ? (
        <>
        {/* ----------------------------------------------------------------
            **ما يفكر فيه الوكيل، ثمّ أين توقّف المسار.**

            موضعُهما فوق المخاطرة والحدود عمداً: السؤال «هل أتدخّل؟» يسبق
            «كم عندي؟». وبطاقةٌ تشرح صمت النظام هي الفراغ الذي وجده بحث
            المنافسين — لا تطبيق من ثمانية عشر يعرض «لماذا لم أتداول».
        ---------------------------------------------------------------- */}
        {s !== null ? (
          <AgentCard
            testID="agent-card"
            tone={verdict.tone}
            title={verdict.verdict}
            body={
              s.no_trade_reason_ar ??
              d?.explanation_ar ??
              'لا سببَ مكتوبٌ لهذه الدورة بعد.'
            }
            chips={
              participation.data?.available === true &&
              Array.isArray(participation.data.steps)
                ? participation.data.steps
                    .filter((step) => step.count !== '—')
                    .map((step) => ({ label: `${step.label_ar} ${step.count}` }))
                : []
            }
          />
        ) : null}

        {/* قسمٌ موجودٌ بلا خطوات ليس مساراً — ولا يُعرض هيكلاً فارغاً. */}
        {participation.data !== null &&
        Array.isArray(participation.data.steps) &&
        participation.data.steps.length > 0 ? (
          <>
            <SectionTitle
              testID="day-path-title"
              title="مسار اليوم"
              note={participation.data.available ? 'أين توقّف' : 'غير معروف'}
              noteTone={participation.data.available ? 'tertiary' : 'caution'}
            />
            <DayPath
              testID="day-path"
              steps={participation.data.steps.map((step) => ({
                label: step.label_ar,
                count: step.count,
                reached: step.reached,
              }))}
              stopAt={
                participation.data.available && participation.data.collapse_in_headline
                  ? participation.data.steps.findIndex(
                      (step) => step.key === participation.data?.collapse_stage,
                    )
                  : null
              }
              note={participation.data.note_ar}
            />
          </>
        ) : null}

        <Card testID="risk-card" title={t.home.risk}>
          {/*
            **أيّ الحدّين يعمل — بنصّ الخادم لا بتفسير العميل.**

            كانت هذه البطاقة تعرض حدود الملف والمحرّك ينفّذ حدود الدستور:
            0.75 لليوم معروضة و6.00 منفَّذة. وشاشةٌ تعد بحدٍّ أشدّ من
            العامل ليست تحفّظاً، هي طمأنينةٌ كاذبة. فالأرقام الآن هي
            المنفَّذة، وهذا السطر يقول ذلك — والفرق يُقال ولا يُخفى.
          */}
          <Text variant="micro" tone="tertiary" testID="risk-binding">
            {r.profile_binding_ar}
          </Text>
          <RiskMeter
            testID="risk-meter-daily"
            label="المتبقّي من مخاطرة اليوم"
            usedLabel={r.risk_used_today}
            remainingLabel={r.risk_remaining_today}
            remainingValue={remainingToday}
            ratio={riskRatio}
          />
          {/*
            «الحدّ» — العنصر التوقيعي. علامته تظهر عند صفر بالمئة أيضاً،
            بخلاف المؤشّر الذي كان يختفي فتبدو الشاشة معطوبة وهي سليمة.
            العتبتان ٦٠٪ و٨٥٪ هما حيث تُضيَّق الأحجام ثم يُمنع الدخول.
          */}
          {riskRatio !== null ? (
            <Hadd
              testID="risk-hadd"
              value={riskRatio}
              max={1}
              label="المستهلَك من حدّ اليوم"
              readout={`${r.risk_used_today ?? '—'} من ${limitToday ?? '—'}`}
              thresholds={[
                { at: 0.6, tone: 'neutral' },
                { at: 0.85, tone: 'negative' },
              ]}
              style={{ marginTop: theme.spacing.sm }}
            />
          ) : null}
          {r.two_loss_lock_active ? (
            <Banner tone="negative" title="قفل الخسارتين مُفعَّل" body="لا دخول جديد اليوم." />
          ) : null}
        </Card>

        {/*
          **حدودٌ يحملها العقد ولا تُعرض.**
        
          `RiskData` يحمل سقفَ المراكز وسقفَ أوامر الدخول اليومية والخسائر
          المتتالية وحدَّي التراجع — ولم يكن **واحدٌ منها** معروضاً. والعيب
          `C2` — أربعةُ مراكز مقابل سقفٍ ثلاثة — كان سيُرى على الشاشة في اليوم
          نفسه لو عُرض حقلان موجودان في العقد أصلاً. الشاشة لا تمنع الخرق
          (المنع في محرّك المخاطر)، لكنها كانت ستكشفه.
        */}
        <Card testID="limits-card" title="الحدود">
          {/*
            **الملفُّ ورأسُ المال المحسوب عليه.** كانا في العقد ولا موضع
            لهما على أيّ شاشة — أمسكهما `no-limit-is-silent`. وحدٌّ بلا
            معرفةِ أيِّ ملفٍّ أنتجه وعلى أيّ رقمٍ حُسب رقمٌ بلا سند.
          */}
          <Field
            label="الملف"
            value={r.profile_name_ar}
            testID="limit-profile-name"
          />
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
          <Divider />
          {/*
            **ثلاثة أرقامٍ للمحفظة لا واحد، والخلاف بينها معلومة.**
            «قيمة المحفظة» في قائمة الخمس ثوانٍ هي `current_equity` تحديداً،
            وهو الرقم الذي كان غائباً.
          */}
          <Field label="المرجعي" value={r.portfolio.baseline_equity} testID="equity-baseline" />
          <Field label="الحالي" value={r.portfolio.current_equity} testID="equity-current" />
          <Field label="لدى الوسيط" value={r.portfolio.broker_equity} testID="equity-broker" />
          {r.portfolio.diverged && r.portfolio.note_ar !== null ? (
            <Text variant="caption" tone="secondary" testID="equity-diverged">
              {r.portfolio.note_ar}
            </Text>
          ) : null}
        </Card>
        </>
      ) : null}

      {/* ---- المركز: الفراغ حالة لا خطأ ---- */}
      {pos !== null && pos.has_position === false ? (
        <Vacancy
          testID="no-position-empty"
          what={t.home.noPosition}
          why={t.home.noPositionWhy}
          next={
            s !== null && !s.market.is_open
              ? `السوق مغلق — ${s.market.reason_ar}`
              : undefined
          }
        />
      ) : null}

      {/* ---- حالة النظام ---- */}
      {s !== null ? (
        <Card testID="system-card" title={t.home.systemState}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <StatusPill
              testID="system-state-pill"
              label={presentSystemPhase(s.system_state, s.system_state_ar).labelAr}
              tone={presentSystemPhase(s.system_state, s.system_state_ar).tone}
            />
            {s.kill_switch.active ? (
              <StatusPill testID="killswitch-pill" label="قاطع الطوارئ مُفعَّل" tone="negative" />
            ) : null}
            {/* الشارة الثانية تظهر فقط إن لم تقلها المرحلة — كانت تُعرض مرّتين. */}
            {s.locally_paused &&
            !presentSystemPhase(s.system_state, s.system_state_ar).labelAr.includes('موقوف') ? (
              <StatusPill testID="paused-pill" label="موقوف محلياً" tone="caution" />
            ) : null}
          </View>

          <Divider />

          <Field
            testID="broker-field"
            label={t.home.brokerConnection}
            value={`${s.broker.name} — ${presentConnection(s.broker.connected).labelAr}`}
            tone={s.broker.connected ? 'positive' : 'negative'}
            /* السبب يسبق النوع حين يوجد: «غير متصل» وحدها لا يُتصرَّف عليها. */
            hint={s.broker.note_ar ?? (s.broker.is_demo ? t.system.demo : t.system.live)}
          />
          {/*
            **نطاق هذه الحالة يُقال، وحالةُ كل أداةٍ تُعرض معها.**

            كانت البطاقة تقول «سوق الفوركس مفتوح» عن ذهبٍ يقول الوسيط إنه
            مقفل — والمحرّك يرفضه بـMARKET_CLOSED في اللحظة نفسها. فقرأت
            المالكة «مفتوح» ولم تفهم لماذا لا يتداول.
          */}
          <Field
            testID="market-field"
            label={t.home.marketStatus}
            value={presentMarket(s.market.is_open).labelAr}
            hint={[s.market.reason_ar, s.market.scope_ar].filter(Boolean).join(' · ')}
          />
          {/* قراءةٌ دفاعية: العقد يعد بالحقل، والاستجابة قد تنقص —
              وشاشةٌ تنهار على حقلٍ ناقص أسوأ من شاشةٍ بلا تفصيل.
              (أسقطها `sparse-data.test.tsx` فور كتابتها.) */}
          {(s.market.per_instrument ?? []).map((row) => (
            <Field
              key={row.symbol}
              testID={`market-instrument-${row.symbol}`}
              label={row.symbol}
              value={row.status}
              hint={row.reason_ar}
              tone={row.tradable === false ? 'caution' : undefined}
            />
          ))}
          <Field
            testID="completeness-field"
            label={t.home.completeness}
            value={`${presentCompleteness(
              s.data_completeness.complete,
              s.data_completeness.missing.length,
            ).labelAr} · ${formatRatio(s.data_completeness.ratio)}`}
            tone={s.data_completeness.complete ? 'positive' : 'caution'}
            /*
              الناقص الإلزامي يُسمّى أولاً لأنه يمنع التداول. والاختياري
              يُذكر بعده **مفصولاً بكلمة تقول إنه لا يمنع** — وخلطُهما هو
              ما جعل «٦٠٪» تبدو حاجزاً وهي ليست كذلك.
            */
            hint={
              [
                s.data_completeness.missing.length > 0
                  ? s.data_completeness.missing.join('، ')
                  : null,
                (s.data_completeness.optional_missing?.length ?? 0) > 0
                  ? `${t.home.optionalMissing}: ${(s.data_completeness.optional_missing ?? []).join('، ')}`
                  : null,
              ]
                .filter(Boolean)
                .join(' · ') || undefined
            }
          />
          <Field
            testID="last-refresh-field"
            label={t.common.lastRefresh}
            value={formatSince(s.last_refresh_utc)}
            hint={formatInstant(s.last_refresh_utc)}
          />
        </Card>
      ) : null}

      {/* ---- تفاصيل الأسبوع ---- */}
      {r !== null ? (
        <Card testID="risk-week-card" title="الأسبوع">
          <Field label="المستهلَك" value={r.risk_used_week} />
          <Field label="المتبقّي" value={r.risk_remaining_week} />
          <Field
            label="المسافة إلى قاطع الطوارئ"
            value={r.distance_to_kill_switch}
            tone="caution"
          />
        </Card>
      ) : null}

      {/* ---- الملف ---- */}
      {p !== null ? (
        <Card testID="profile-card" title={t.home.profile}>
          <Field label={t.profiles.selected} value={p.selected_name_ar ?? p.selected_profile} />
          <Field label={t.profiles.effective} value={p.effective_name_ar ?? p.effective_profile} />
          {p.pending_profile !== null ? (
            <Field
              label={t.profiles.pending}
              value={p.pending_profile}
              hint={`${t.profiles.coolingRemaining}: ${formatCooling(
                p.cooling_remaining_seconds,
              )}`}
              tone="caution"
            />
          ) : null}
          <NavRow
            testID="nav-profiles"
            label={t.nav.profiles}
            hint={t.profiles.cannotChange}
            href="/(app)/profiles"
          />
        </Card>
      ) : null}

      {/* ---- القرار ---- */}
      {d !== null ? (
        <Card testID="decision-card" title={t.home.decision}>
          <StatusPill
            testID="decision-pill"
            label={presentDecision(d.decision, d.decision_ar).labelAr}
            tone={presentDecision(d.decision, d.decision_ar).tone}
          />
          <Field
            testID="score-field"
            label={t.home.score}
            value={d.score === null ? null : `${d.score.total} / ${d.score.max}`}
            large
          />
          <NavRow
            testID="nav-decision"
            label={t.nav.decision}
            hint={t.decision.descriptiveOnly}
            href="/(app)/decision"
          />
        </Card>
      ) : null}

      {/* ---- الاستراتيجية ---- */}
      {s !== null && s.strategy_state !== null ? (
        <Card testID="strategy-card" title={t.home.strategy}>
          <Field label="الاستراتيجية" value={s.strategy_state.title_ar} />
          <Field
            label="الحالة"
            value={s.strategy_state.state}
            tone={s.strategy_state.live_eligible ? 'positive' : 'caution'}
            hint={
              s.strategy_state.live_eligible
                ? 'مُجازة للتنفيذ على الخادم.'
                : 'غير مُجازة للتنفيذ بعد.'
            }
          />
        </Card>
      ) : null}

      {/* ---- الحدث القادم ---- */}
      <Card testID="event-card" title={t.home.upcomingEvent}>
        {s !== null && s.upcoming_event !== null ? (
          <>
            <Field label="الحدث" value={s.upcoming_event.title_ar} />
            <Field
              label="الوقت"
              value={formatInstant(s.upcoming_event.at_utc)}
              hint={s.upcoming_event.impact_ar}
              tone={s.upcoming_event.blocks_trading ? 'caution' : 'primary'}
            />
          </>
        ) : (
          <Text variant="caption" tone="tertiary" testID="no-event">
            {t.home.noEvent}
          </Text>
        )}
      </Card>

      {/* ---- المركز الحالي ---- */}
      <Card testID="position-card" title={t.home.position}>
        {pos !== null && pos.has_position ? (
          <>
            <Field label={t.position.instrument} value={pos.instrument_ar ?? pos.instrument} />
            <Field label={t.position.direction} value={pos.direction_ar} />
            {/*
              الربح غير المحقّق: الرقم الوحيد في التطبيق الذي يتحرّك لحظياً.
              يأخذ الإشارة `+` أو `−` مع اللون — فاللون يعطي السرعة، والإشارة
              تضمن أن المعنى لا يضيع في التدرّج الرمادي ولا عند عمى الألوان.
            */}
            <View style={{ gap: theme.spacing.xs }}>
              <Text variant="caption" tone="secondary">
                {t.position.unrealised}
              </Text>
              {unrealised !== null ? (
                <AnimatedNumber
                  value={unrealised}
                  decimals={2}
                  unit="دولار"
                  variant="numericLarge"
                  signed
                  testID="unrealised-pnl"
                />
              ) : (
                <Text
                  variant="numericLarge"
                  tone={presentPnlTone(pos.unrealised_pnl_sign)}
                  tabular
                  testID="unrealised-pnl"
                >
                  {pos.unrealised_pnl ?? '—'}
                </Text>
              )}
            </View>
            <NavRow
              testID="nav-position"
              label={t.nav.position}
              hint={t.position.cannotModify}
              href="/(app)/position"
            />
          </>
        ) : (
          <Text variant="caption" tone="tertiary" testID="no-position">
            {t.home.noPosition}
          </Text>
        )}
      </Card>

      {/* التنقّل صار في شريط التبويبات أسفل الشاشة — لا قائمةً مرسومة كبطاقة. */}

      <Text variant="micro" tone="tertiary" testID="home-no-execution">
        {t.common.noExecution}
      </Text>
    </Screen>
  );
}
