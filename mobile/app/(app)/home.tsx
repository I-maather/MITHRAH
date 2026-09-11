import React, { useCallback } from 'react';
import { View } from 'react-native';

import { sumOf } from '@/api/positionTotals';
import { useEndpoint } from '@/api/useEndpoint';
import { ApiError } from '@/api/client';
import { LinearGradient } from 'expo-linear-gradient';
import {
  AgentCard,
  Banner,
  CandleChart,
  Card,
  DayPath,
  ErrorState,
  Glass,
  LoadingState,
  NavRow,
  OfflineBanner,
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
import { fontFamilies } from '@/theme/tokens';
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
/**
 * عنوانُ بطاقة المراكز — بالعدد لا بعبارةٍ عامّة.
 *
 * «مراكز تحتاج انتباهك» لا تقول كم، والعددُ أوّلُ ما يُسأل عنه.
 * و`null` تعني «تعذّرت القراءة» لا «صفر» — فتُقال كما هي.
 */
function openPositionsTitle(count: number | null): string {
  if (count === null) {
    return 'المراكزُ المفتوحة — تعذّرت القراءة';
  }
  if (count === 1) {
    return 'مركزٌ واحدٌ مفتوح';
  }
  if (count === 2) {
    return 'مركزان مفتوحان';
  }
  if (count >= 3 && count <= 10) {
    return count + ' مراكزَ مفتوحة';
  }
  return count + ' مركزاً مفتوحاً';
}

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
    /** آخرُ سعرٍ رآه القرار لهذه الأداة — أو `null` إن لم يصل. */
    live: number | null;
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
    const rawLive = Number(cd.live?.[symbol]?.price);
    const live = Number.isFinite(rawLive) ? rawLive : null;
    return prepared === null ? null : { symbol, resolution, prepared, levels, live };
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

  /**
   * **المخاطرةُ المفتوحة** — مجموعُ ما يخسره كلُّ مركزٍ عند وقفه.
   *
   * هي ما يعرضه النموذج في هذا الموضع، لا المستهلَك من الحدّ. والمجموعُ
   * الناقص يُعلَن ناقصاً: `missing` تقول كم مركزاً بلا قيمة.
   */
  const openRisk = sumOf(pos?.positions ?? [], 'risk_at_stop');

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

  /** ما يملأ شريطَ الحرارة: المفتوحةُ من الحدّ إن عُرفت، وإلا المستهلَك. */
  const heatRatio = ((): number | null => {
    const limit = Number(limitToday);
    if (openRisk.value !== null && Number.isFinite(limit) && limit > 0) {
      return openRisk.value / limit;
    }
    return riskRatio;
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
      // الشعارُ صار في الرأس، وكتابتُه هنا ثانيةً تكرارٌ رأته المالكة.
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
          {/*
            **السببُ يُقال مرّةً واحدة — في بطاقة الوكيل.**

            كان يُكتب هنا نصّاً، ثم يُكتب متناً في البطاقة نفسها بعد سطور.
            ورُئي على الجهاز يوم ٦ سبتمبر: الجملةُ ذاتها **ثلاثَ مرّات** في
            شاشةٍ واحدة، والحكمُ مرّتين. وتكرارُ الجملة لا يؤكّدها — يجعل
            الشاشة تبدو معطوبة.
          */}
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
        <Glass testID="allocated-card" padding={18}>
          {/* `.gtop` — الاسمُ يميناً وحبّةُ المزامنة يساراً. */}
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 10,
            }}
          >
            <Text variant="micro" tone="secondary" style={{ fontSize: 10 }}>
              {t.home.allocated}
            </Text>
            {s !== null ? (
              <View
                testID="sync-chip"
                style={{
                  borderRadius: 20,
                  paddingVertical: 4,
                  paddingHorizontal: 9,
                  backgroundColor: theme.colors.accentSoft,
                  borderWidth: 1,
                  borderColor: theme.colors.accentSoft,
                }}
              >
                <Text variant="micro" style={{ fontSize: 9, color: theme.colors.caution }}>
                  {formatSince(s.last_refresh_utc)}
                </Text>
              </View>
            ) : null}
          </View>

          {/* `.gbal` — 33 بوزن 800، والرقمُ يسارُ الاتجاه دائماً. */}
          <View style={{ marginTop: 11, marginBottom: 3 }}>
            {/*
              `.gbal` — 33 بوزن 800. ولا عدَّ متدرّجاً هنا: النموذج رقمٌ
              ساكن، والحركةُ في رقمٍ بهذا الحجم تجذب العين إلى التغيّر لا
              إلى القيمة. والحركةُ باقيةٌ حيث تنفع — الربحُ غير المحقَّق.

              و«لم يصل» تُعرض «غير متاح» بحجمٍ أصغر وبلا لونٍ — `.gbal.na`
              في النموذج — فلا يُقرأ الجهلُ رقماً.
            */}
            {allocated !== null ? (
              <Text
                variant="numericLarge"
                tabular
                testID="allocated-equity"
                accessibilityLabel={`${t.home.allocated}: ${allocated.toFixed(2)} دولار`}
                style={{ fontSize: 33, fontFamily: fontFamilies.numeric['800'] }}
              >
                {allocated.toFixed(2)}
              </Text>
            ) : (
              <Text
                variant="numericLarge"
                testID="allocated-equity"
                style={{ fontSize: 21, color: theme.colors.textTertiary }}
              >
                {r.portfolio?.current_equity ?? 'غير متاح'}
              </Text>
            )}
          </View>

          {/* `.gsub` — المحقَّق اليوم، أو الفرقُ عن المرجعي حتى يصل الحقل. */}
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
            {delta !== null ? (
              <Text
                variant="micro"
                tabular
                testID="allocated-delta"
                style={{
                  fontSize: 10.5,
                  color:
                    delta < 0
                      ? theme.colors.negative
                      : delta > 0
                        ? theme.colors.positive
                        : theme.colors.textSecondary,
                }}
              >
                {`${delta < 0 ? '−' : '+'}${Math.abs(delta).toFixed(2)}`}
              </Text>
            ) : null}
            <Text
              variant="micro"
              tone="tertiary"
              testID="allocated-baseline"
              style={{ fontSize: 10.5 }}
            >
              {`عن المرجعي ${r.portfolio?.baseline_equity ?? '—'}`}
            </Text>
          </View>

          {/* `.grow` — المخاطرةُ المفتوحة من حدّ اليوم. */}
          <View
            style={{
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 10,
              marginTop: 14,
            }}
          >
            <Text variant="micro" tone="secondary" style={{ fontSize: 10 }}>
              {openRisk.value === null ? 'المستهلَك من مخاطرة اليوم' : 'المخاطرة المفتوحة'}
            </Text>
            <Text
              variant="micro"
              tabular
              testID="open-risk"
              style={{ fontSize: 10.5, fontFamily: fontFamilies.numeric['700'] }}
            >
              {`${
                openRisk.value === null
                  ? (r.risk_used_today ?? '—')
                  : openRisk.value.toFixed(2)
              } / ${limitToday ?? '—'}`}
            </Text>
          </View>

          {/* `.heat` — شريطٌ 7px بتدرّج الجمر→المرجان. */}
          <View
            testID="heat-bar"
            accessible
            accessibilityLabel={`${heatRatio === null ? 'غير معروف' : `${Math.round(heatRatio * 100)}٪`} من حدّ اليوم`}
            style={{
              height: 7,
              borderRadius: 8,
              marginTop: 8,
              overflow: 'hidden',
              backgroundColor: theme.colors.surfaceSunken,
              borderWidth: 1,
              borderColor: theme.colors.border,
            }}
          >
            {heatRatio !== null ? (
              <LinearGradient
                colors={
                  heatRatio >= 1
                    ? [theme.colors.negative, theme.colors.negative]
                    : [theme.colors.accent, theme.colors.accentGlow]
                }
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
                style={{ height: '100%', width: `${Math.min(100, heatRatio * 100)}%` }}
              />
            ) : null}
          </View>

          {/*
            أيُّ الحدّين يعمل — بنصّ الخادم. ليس في النموذج، ولا يُحذف:
            شاشةٌ تَعِد بحدٍّ أشدّ من العامل طمأنينةٌ كاذبة. فيبقى سطراً
            هادئاً 9px لا بطاقةً تُزاحم.
          */}
          <Text
            variant="micro"
            tone="tertiary"
            testID="risk-binding"
            style={{ fontSize: 9, marginTop: 9, lineHeight: 15 }}
          >
            {r.profile_binding_ar}
          </Text>
          {r.two_loss_lock_active ? (
            <Banner tone="negative" title="قفل الخسارتين مُفعَّل" body="لا دخول جديد اليوم." />
          ) : null}
        </Glass>
      ) : null}

      {/* ----------------------------------------------------------------
          **ما يفكر فيه الوكيل، ثمّ أين توقّف المسار.**

          بطاقةٌ تشرح صمت النظام هي الفراغ الذي وجده بحث المنافسين — لا
          تطبيق من ثمانية عشر يعرض «لماذا لم أتداول».

          ولم تعد مشروطةً بوصول بيانات المخاطر: كانت داخل `r !== null`،
          فتختفي أوضحُ جملةٍ في الشاشة حين يتعذّر أقلُّ حقلٍ فيها صلةً بها.
      ---------------------------------------------------------------- */}
      {s !== null ? (
        <>
          <SectionTitle title="ما يفكر فيه الوكيل" note="مباشر" noteTone="tertiary" />
          <AgentCard
            testID="agent-card"
            tone={verdict.tone}
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
        </>
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
          <CandleChart
            testID="home-chart"
            prepared={home.prepared}
            height={188}
            livePrice={home.live}
          />
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

      {/* ----------------------------------------------------------------
          **كلُّ المراكز، لا أوّلُها.**

          كانت هذه البطاقة تقرأ الحقولَ المفردة `pos.instrument_ar` و
          `pos.direction_ar` و`pos.unrealised_pnl`. وعقدُ الخادم يقول عنها
          صراحةً إنها **تصف أوّل مركزٍ مفتوح — للشاشة القديمة**. فبمركزَين
          مفتوحَين كانت الشاشة تعرض واحداً وتصمت عن الثاني، ولا تقول العدد
          أصلاً. وهو ما قالته المالكة بالحرف: «ما اعرف كم صفقة مفتوحة وايش
          وضعهم».

          الآن: العددُ في العنوان، والإجماليُّ رقماً كبيراً، ثمّ صفٌّ لكلّ
          مركزٍ بحاله — وما يستحقّ الانتباه (وقفٌ غير مثبَّتٍ عند الوسيط،
          أو مركزٌ لم يُؤكَّد في القراءة الأخيرة) يُقال في مكانه لا يُطوى.
      ---------------------------------------------------------------- */}
      {pos !== null && pos.has_position ? (
        <Card testID="attention-card" title={openPositionsTitle(pos.open_count)}>
          <View style={{ gap: theme.spacing.xs }}>
            <Text variant="caption" tone="secondary">
              {t.position.unrealised}
            </Text>
            <Text
              variant="numericLarge"
              tone={presentPnlTone(pos.unrealised_pnl_sign)}
              tabular
              testID="unrealised-pnl"
            >
              {pos.total_unrealised ?? pos.unrealised_pnl ?? '—'}
            </Text>
          </View>

          {(pos.positions ?? []).map((row, index) => (
            <View
              key={row.id ?? `${row.instrument ?? 'x'}-${index}`}
              style={{ gap: 2 }}
              testID={`open-position-${index}`}
            >
              <View
                style={{
                  flexDirection: 'row',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  gap: theme.spacing.sm,
                }}
              >
                <Text variant="body">{row.instrument_ar ?? row.instrument ?? '—'}</Text>
                <Text variant="numeric" tone={presentPnlTone(row.unrealised_pnl_sign)} tabular>
                  {row.unrealised_pnl ?? '—'}
                </Text>
              </View>
              <Text variant="caption" tone="tertiary">
                {[
                  row.direction_ar,
                  row.size_display,
                  row.entry_price !== null ? `دخول ${row.entry_price}` : null,
                  row.stop_price !== null ? `وقف ${row.stop_price}` : null,
                  row.risk_at_stop !== null ? `مخاطرة ${row.risk_at_stop}` : null,
                ]
                  .filter((part) => part !== null && part !== undefined && part !== '')
                  .join(' · ')}
              </Text>
              {!row.protection_held_by_broker ? (
                <Text variant="caption" tone="negative">
                  الوقفُ غير مثبَّتٍ عند الوسيط.
                </Text>
              ) : null}
              {row.reconciliation === 'STALE' ? (
                <Text variant="caption" tone="caution">
                  لم يُؤكَّد في آخر قراءة — يُعرَض من الدفتر.
                </Text>
              ) : null}
            </View>
          ))}

          <NavRow
            testID="nav-position"
            label={t.nav.position}
            hint={t.position.cannotModify}
            href="/(app)/position"
          />
        </Card>
      ) : null}

      {/*
        **صفٌّ لا بطاقةٌ داخل بطاقة.**

        كان صفُّ الانتقال ملفوفاً ببطاقةٍ عنوانُها «بقيّة هذا القسم» — علبةٌ
        حول علبةٍ حول سطر. ورُئي على الجهاز فبدا حشواً.
      */}
      <NavRow
        testID="nav-decision"
        label={t.nav.decision}
        hint={t.decision.descriptiveOnly}
        href="/(app)/decision"
      />

      {/* التنقّل صار في شريط التبويبات أسفل الشاشة — لا قائمةً مرسومة كبطاقة. */}

      <Text variant="micro" tone="tertiary" testID="home-no-execution">
        {t.common.noExecution}
      </Text>
    </Screen>
  );
}
