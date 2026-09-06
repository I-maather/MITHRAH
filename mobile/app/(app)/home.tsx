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
  NavRow,
  OfflineBanner,
  RiskMeter,
  Screen,
  StaleBanner,
  SectionTitle,
  Text,
  Welcome,
  Vacancy,
  prepareChart,
  spanLabel,
  type ChartLevel,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatSince, formatToday, t } from '@/i18n';
import { useTheme } from '@/theme';
import { dayVerdict } from '@/utils/verdict';
import {
  presentPnlTone,
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
    position.refresh();
    candles.refresh();
  }, [status, decision, risk, position, candles]);

  const offline =
    status.error instanceof ApiError && status.error.kind === 'OFFLINE';
  const anyLoading = status.loading && status.data === null;

  const s = status.data;
  const d = decision.data;
  const r = risk.data;
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

  /** الحصّة المخصَّصة رقماً — للعدّ المتدرّج. نصٌّ لا يُقرأ ⇒ `null` بلا تخمين. */
  const allocated = ((): number | null => {
    const v = Number(r?.portfolio?.current_equity?.replace(/,/g, ''));
    return Number.isFinite(v) ? v : null;
  })();

  /** المرجعيّ رقماً — يُقاس عليه الفرق، ولا يُعرض الفرقُ بدونه. */
  const baselineNumber = ((): number | null => {
    const v = Number(r?.portfolio?.baseline_equity?.replace(/,/g, ''));
    return Number.isFinite(v) ? v : null;
  })();

  const delta =
    allocated !== null && baselineNumber !== null ? allocated - baselineNumber : null;

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

      {/* ----------------------------------------------------------------
          **الرقمُ الرئيسي — رقمٌ واحدٌ يجيب «كم عندي».**

          كانت هنا بطاقةٌ تعرض رصيدَ الوسيط والمرجعيَّ **ندّين متساويي
          الوزن**، فلا تقول أيُّهما الجواب. وقرارُك المعتمد أنّ الحصّة
          المخصَّصة هي المقياس، ورصيدَ الوسيط معلومةُ كفايةِ هامشٍ لا
          مقياس — فنزل إلى «النظام»، وبقي هنا رقمٌ واحدٌ كبير كما في
          النموذج المعتمد، وتحته ما يقيس عليه: المرجعيُّ والفرق.

          والمخاطرةُ معه في البطاقة نفسها لا في بطاقةٍ تالية: «كم عندي»
          و«كم يجوز أن أخسر اليوم» سؤالٌ واحد في النموذج.
      ---------------------------------------------------------------- */}
      {r !== null ? (
        <Card
          testID="allocated-card"
          title={t.home.allocated}
          variant="glass"
        >
          {allocated !== null ? (
            <AnimatedNumber
              value={allocated}
              decimals={2}
              unit="دولار"
              variant="numericLarge"
              testID="allocated-equity"
            />
          ) : (
            <Text variant="numericLarge" tabular testID="allocated-equity">
              {r.portfolio?.current_equity ?? '—'}
            </Text>
          )}
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <Text variant="caption" tone="secondary" testID="allocated-baseline">
              {`من ${r.portfolio?.baseline_equity ?? '—'} مخصَّصة`}
            </Text>
            {/*
              الفرقُ عن المرجعي يُشتقّ من رقمين على الكائن نفسه — ولا يُسمّى
              «محقَّقاً»: هو المحقَّق وغيرُ المحقَّق معاً على الحصّة، وتسميتُه
              محقَّقاً دعوى لا يحملها العقد.
            */}
            {delta !== null ? (
              <Text
                variant="caption"
                tone={delta < 0 ? 'negative' : delta > 0 ? 'positive' : 'secondary'}
                tabular
                testID="allocated-delta"
              >
                {`${delta < 0 ? '−' : '+'}${Math.abs(delta).toFixed(2)} عن المرجعي`}
              </Text>
            ) : null}
          </View>
          {s !== null ? (
            <Text variant="micro" tone="tertiary" testID="allocated-freshness">
              {formatSince(s.last_refresh_utc)}
            </Text>
          ) : null}

          <Divider />

          {/*
            **أيّ الحدّين يعمل — بنصّ الخادم لا بتفسير العميل.**

            كانت هذه تعرض حدود الملف والمحرّك ينفّذ حدود الدستور: 0.75
            معروضة و6.00 منفَّذة. وشاشةٌ تعد بحدٍّ أشدّ من العامل ليست
            تحفّظاً، هي طمأنينةٌ كاذبة.
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
      ) : null}

      {/* ----------------------------------------------------------------
          **ما يفكر فيه الوكيل، ثمّ أين توقّف المسار.**

          بطاقةٌ تشرح صمت النظام هي الفراغ الذي وجده بحث المنافسين — لا
          تطبيق من ثمانية عشر يعرض «لماذا لم أتداول».

          ولم تعد مشروطةً بوصول بيانات المخاطر: كانت داخل `r !== null`،
          فتختفي أوضحُ جملةٍ في الشاشة حين يتعذّر أقلُّ حقلٍ فيها صلةً بها.
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

      {/* ----------------------------------------------------------------
          **وهنا تنتهي الشاشة — عند المراكز، كما في النموذج.**

          كان بعد هذا الموضع عشرُ بطاقات: النظام والأسبوع والملف والقرار
          والاستراتيجية والحدث والحدود والمركز. انتقلت إلى تبويبيها:
          ما يخصّ التشغيل والإصدار إلى «النظام»، وما يخصّ المراكز والحدود
          إلى «المحفظة». والشاشةُ التي كلُّ شيءٍ فيها مهمّ لا شيءَ فيها مهمّ.
      ---------------------------------------------------------------- */}
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

      {pos !== null && pos.has_position ? (
        <Card testID="attention-card" title={t.home.attention}>
          <Field label={t.position.instrument} value={pos.instrument_ar ?? pos.instrument} />
          <Field label={t.position.direction} value={pos.direction_ar} />
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
        </Card>
      ) : null}

      {/* القرارُ شرحٌ لا أمر — صفُّ انتقالٍ يكفيه، وبطاقةٌ كاملة تُثقل. */}
      <Card testID="today-more-card" title={t.nav.more}>
        <NavRow
          testID="nav-decision"
          label={t.nav.decision}
          hint={t.decision.descriptiveOnly}
          href="/(app)/decision"
        />
      </Card>

      {/* التنقّل صار في شريط التبويبات أسفل الشاشة — لا قائمةً مرسومة كبطاقة. */}

      <Text variant="micro" tone="tertiary" testID="home-no-execution">
        {t.common.noExecution}
      </Text>
    </Screen>
  );
}
