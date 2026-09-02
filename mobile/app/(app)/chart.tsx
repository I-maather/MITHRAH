import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import type { Candle } from '@/api/types';
import {
  Banner,
  Button,
  CandleChart,
  Card,
  Divider,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  Text,
  Vacancy,
  prepareChart,
  type ChartLevel,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * شاشة الشموع.
 *
 * ## ما هي، وما ليست
 *
 * هي **السعر كما رآه النظام حين قرّر**، وعليه دخوله ووقفه وهدفه. وليست شاشة
 * تداول: لا زرّ شراء ولا بيع — ولا يملك هذا التطبيق مساراً إليهما أصلاً
 * (`src/api/routes.ts`، ويحرسه `__tests__/security-boundary.test.ts`).
 *
 * ## لماذا ليست «مباشرة»
 *
 * الشموع تأتي من ذاكرة الخادم لا من الوسيط، فهي صورة آخر دورة مسح. وهذا
 * أصدق من الأحدث: شمعةٌ أحدث من القرار تجعل السبب المكتوب في شاشة «القرار»
 * يبدو خاطئاً وهو صحيح على بياناته. والنصّ يقول ذلك ولا يُكتب «مباشر».
 *
 * ## المستويات
 *
 * تُرسَم لأداة المركز وحدها. ورسمُها فوق أداةٍ أخرى يعني خطّ وقفٍ عند
 * 1.10 على رسم ذهبٍ عند 2400 — وهو ليس خطأً في المقياس بل كذبةٌ في المعنى.
 */
export default function ChartScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getCandles(), {
    previewData: previewOr(fixtures.candles),
  });

  const [chosen, setChosen] = React.useState<string | null>(null);
  const [frame, setFrame] = React.useState<string | null>(null);

  if (loading && data === null) {
    return (
      <Screen title={t.chart.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.chart.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const symbols = data.symbols ?? [];
  /**
   * الأداة المعروضة. الافتراض **أداة المركز إن وُجد** — فهي التي تعني المالكة
   * الآن — ثم أول رمز. واختيارٌ لم يعد في القائمة يسقط إلى الافتراض بدل أن
   * يترك الشاشة فارغة بلا سبب.
   */
  const fallback = symbols.includes(data.levels.symbol ?? '')
    ? (data.levels.symbol as string)
    : (symbols[0] ?? null);
  const active = chosen !== null && symbols.includes(chosen) ? chosen : fallback;
  const perFrame: Record<string, Candle[]> =
    active === null ? {} : (data.instruments[active] ?? {});

  /**
   * الإطار المعروض. الافتراض **إطار القرار** — فهو ما يُقاس عليه فعلاً،
   * وعرضُ غيره ابتداءً يوحي بأن النظام يقرّر عليه.
   */
  const available = (data.resolutions ?? []).filter((r) => perFrame[r] !== undefined);
  const fallbackFrame = available.includes(data.decision_resolution)
    ? data.decision_resolution
    : (available[0] ?? null);
  const activeFrame = frame !== null && available.includes(frame) ? frame : fallbackFrame;
  const candles: Candle[] = activeFrame === null ? [] : (perFrame[activeFrame] ?? []);

  /**
   * المستويات — لأداة المركز وحدها، وبعد قراءتها أرقاماً.
   * وما لا يُقرأ رقماً لا يُرسَم: خطٌّ في موضعٍ مخمَّن أسوأ من غيابه.
   */
  const levels: ChartLevel[] =
    active !== null && data.levels.symbol === active
      ? ([
          { key: 'entry' as const, label: t.chart.entry, raw: data.levels.entry, color: theme.colors.textPrimary },
          { key: 'stop' as const, label: t.chart.stop, raw: data.levels.stop, color: theme.colors.negative },
          { key: 'target' as const, label: t.chart.target, raw: data.levels.target, color: theme.colors.positive },
        ]
          .map((row) => ({ ...row, value: Number(row.raw) }))
          .filter((row) => row.raw !== null && Number.isFinite(row.value))
          .map(({ key, label, value, color }) => ({ key, label, value, color })) as ChartLevel[])
      : [];

  /**
   * التجهيز دالّةٌ خالصة تُستدعى هنا — **ولا حالة تُشتقّ من حالة**.
   *
   * وكان المكوّن يعيد المقياس عبر `onScale` في أثر، فتدور حلقةٌ لا تنتهي:
   * `candles` و`levels` تُبنيان في كل تصيير فتختلف هويّتهما. ونفدت الذاكرة
   * في jest قبل أن يصل ذلك إلى جهاز.
   */
  const prepared = prepareChart(candles, levels);

  const closes = candles.map((c) => Number(c.c)).filter((n) => Number.isFinite(n));
  const highs = candles.map((c) => Number(c.h)).filter((n) => Number.isFinite(n));
  const lows = candles.map((c) => Number(c.l)).filter((n) => Number.isFinite(n));

  return (
    <Screen
      testID="chart-screen"
      title={t.chart.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Banner testID="chart-note" tone="info" title={data.note_ar} body={t.chart.intro} />

      {symbols.length === 0 || prepared === null ? (
        <Vacancy
          testID="chart-empty"
          what={t.chart.noCandlesYet}
          why={t.chart.noCandlesWhy}
          tone="fault"
        />
      ) : (
        <>
          {/* منتقي الأداة — أزرارٌ لا قائمة منسدلة: أربع أدوات تُرى كلها
              دفعةً واحدة، والمنسدلة تُخفي ثلاثاً منها خلف لمسة. */}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
            {symbols.map((symbol) => (
              <View key={symbol} style={{ minWidth: 96 }}>
                <Button
                  testID={`chart-pick-${symbol}`}
                  label={symbol}
                  kind={symbol === active ? 'primary' : 'secondary'}
                  onPress={() => {
                    setChosen(symbol);
                  }}
                  accessibilityLabel={`${t.chart.pickInstrument}: ${symbol}`}
                  accessibilityHint="يعرض شموع هذه الأداة"
                />
              </View>
            ))}
          </View>

          {/* منتقي الإطار. وإطار القرار موسومٌ صراحةً: تصفّح إطارٍ آخر
              لا يعني أن النظام يقرّر عليه، وقيدُ الوسيط يمنع التداول على
              ما دون اليومي أصلاً. */}
          {available.length > 1 ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
              {available.map((resolution) => (
                <View key={resolution} style={{ minWidth: 88 }}>
                  <Button
                    testID={`chart-frame-${resolution}`}
                    label={
                      resolution === data.decision_resolution
                        ? `${t.chart.frames[resolution] ?? resolution} ★`
                        : (t.chart.frames[resolution] ?? resolution)
                    }
                    kind={resolution === activeFrame ? 'primary' : 'secondary'}
                    onPress={() => {
                      setFrame(resolution);
                    }}
                    accessibilityLabel={`${t.chart.frame}: ${t.chart.frames[resolution] ?? resolution}`}
                    accessibilityHint={
                      resolution === data.decision_resolution
                        ? t.chart.decisionFrameHint
                        : t.chart.viewOnlyFrameHint
                    }
                  />
                </View>
              ))}
            </View>
          ) : null}

          <Card testID="chart-card" title={`${active ?? '—'} · ${t.chart.frames[activeFrame ?? ''] ?? activeFrame ?? ''}`}>
            {activeFrame !== null && activeFrame !== data.decision_resolution ? (
              <Text variant="caption" tone="caution" testID="chart-view-only">
                {t.chart.viewOnly}
              </Text>
            ) : null}
            <CandleChart testID="chart-canvas" prepared={prepared} />

            <View style={{ flexDirection: 'row', gap: theme.spacing.lg }}>
              <View style={{ flex: 1 }}>
                <Field label={t.chart.bars} value={String(candles.length)} />
              </View>
              <View style={{ flex: 1 }}>
                <Field
                  label={t.chart.last}
                  value={closes.length > 0 ? String(closes[closes.length - 1]) : null}
                />
              </View>
            </View>
            <View style={{ flexDirection: 'row', gap: theme.spacing.lg }}>
              <View style={{ flex: 1 }}>
                <Field label={t.chart.high} value={highs.length > 0 ? String(Math.max(...highs)) : null} />
              </View>
              <View style={{ flex: 1 }}>
                <Field label={t.chart.low} value={lows.length > 0 ? String(Math.min(...lows)) : null} />
              </View>
            </View>

            {prepared.dropped > 0 ? (
              <Text variant="caption" tone="caution" testID="chart-dropped">
                {t.chart.unreadable}
              </Text>
            ) : null}
          </Card>

          <Card testID="chart-levels-card" title={t.chart.levelsOn}>
            {levels.length === 0 ? (
              <Text variant="caption" tone="secondary" testID="chart-no-levels">
                {t.chart.noPosition}
              </Text>
            ) : (
              <>
                <Field label={t.chart.levelsOn} value={data.levels.symbol} />
                <Divider />
                {levels.map((level) => (
                  <Field
                    key={level.key}
                    testID={`chart-level-value-${level.key}`}
                    label={level.label}
                    value={String(level.value)}
                    tone={
                      level.key === 'stop' ? 'negative' : level.key === 'target' ? 'positive' : 'primary'
                    }
                  />
                ))}
                {prepared.scale.offChart.length > 0 ? (
                  <Text variant="caption" tone="caution" testID="chart-off-scale">
                    {t.chart.levelsOffChart}
                  </Text>
                ) : null}
              </>
            )}
          </Card>
        </>
      )}
    </Screen>
  );
}
