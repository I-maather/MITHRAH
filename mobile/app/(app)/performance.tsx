import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Metric,
  Screen,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, formatRatio, t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * الأداء والمعايرة.
 *
 * القاعدة الحاكمة هنا: **العيّنة الصغيرة لا تُقرأ**. حين يقول الخادم إن العيّنة
 * غير كافية، لا تُعرض نسبة ربح ولا توقّع ولا متوسط R — تُعرض ملاحظة تقول ذلك
 * صراحةً. رقمٌ من ثلاث صفقات يبدو معرفة وهو ضجيج.
 */
export default function PerformanceScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getPerformance(), {
    previewData: previewOr(fixtures.performance),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.performance.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.performance.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const sufficient = data.sufficient_sample;

  return (
    <Screen
      testID="performance-screen"
      title={t.performance.title}
      subtitle={
        data.period_start_utc === null
          ? undefined
          : `${t.performance.period}: ${formatInstant(data.period_start_utc)} — ${formatInstant(
              data.period_end_utc,
            )}`
      }
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {!sufficient ? (
        <Banner
          testID="insufficient-sample-banner"
          tone="caution"
          title={t.performance.insufficient}
          body={data.insufficient_sample_note_ar ?? undefined}
        />
      ) : null}

      <Card testID="performance-summary-card" title="الملخّص">
        <View style={{ flexDirection: 'row', gap: theme.spacing.xl }}>
          <Metric testID="sample-size" label={t.performance.sample} value={data.sample_size} />
          <Metric
            testID="win-rate"
            label={t.performance.winRate}
            value={sufficient ? formatRatio(data.win_rate) : null}
            caption={sufficient ? undefined : t.performance.insufficient}
          />
        </View>
        <Divider />
        <Field label={t.performance.wins} value={data.wins} />
        <Field label={t.performance.losses} value={data.losses} />
        <Field
          label={t.performance.averageR}
          value={sufficient ? data.average_r : null}
          hint={sufficient ? undefined : t.performance.insufficient}
        />
        <Field
          label={t.performance.expectancy}
          value={sufficient ? data.expectancy : null}
          hint={sufficient ? undefined : t.performance.insufficient}
        />
        <Field label={t.performance.maxDrawdown} value={data.max_drawdown} tone="caution" />
        <Field label={t.performance.totalPnl} value={data.realised_pnl_total} />
      </Card>

      <Card
        testID="calibration-card"
        title={t.performance.calibration}
        subtitle="المتوقَّع مقابل المُلاحَظ"
      >
        {data.calibration.length === 0 ? (
          <EmptyState message={t.common.notComputed} />
        ) : (
          data.calibration.map((bucket, index) => (
            <View key={bucket.band_ar} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <Text variant="bodyStrong">{bucket.band_ar}</Text>
              <Field label={t.performance.predicted} value={formatRatio(bucket.predicted)} />
              <Field
                label={t.performance.observed}
                value={bucket.sufficient ? formatRatio(bucket.observed) : null}
                hint={bucket.sufficient ? undefined : 'العيّنة أصغر من أن تُقرأ.'}
              />
              <Field label={t.performance.bucketSample} value={bucket.sample_size} />
            </View>
          ))
        )}
      </Card>
    </Screen>
  );
}
