import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import type { ScanInstrument } from '@/api/types';
import {
  Banner,
  Card,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  StatusPill,
  Text,
  Vacancy,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * «ماذا رأيتُ اليوم» — الشاشة التي يخلو منها كل منافس.
 *
 * ## لماذا هي هنا
 *
 * بحث المنافسين في هذا المشروع فحص ٦٩ لقطة من ١٨ تطبيقاً ولم يجد **شاشةً
 * واحدة** تقول «لماذا لم أتداول». وكل ما تعرضه تلك التطبيقات هو الرصيد
 * والمراكز — أي ما فعله المستخدم، لا ما رآه النظام.
 *
 * والنظام هنا يمسح أدواته كل دقيقة ويكتب سبباً لكل واحدة. وكان ذلك محفوظاً
 * في الذاكرة ولا يصل إلى صاحبته.
 *
 * ## قاعدة العرض
 *
 * **الصمت عملٌ لا عطل.** «رأيتُ السوق ولم أجد فرصة» هو النظام يعمل تماماً
 * كما صُمّم؛ و«لم أرَ السوق» عطلٌ يحتاج يداً. وعرضُهما بلونٍ واحد يجعل
 * المالكة إمّا تقلق كل يوم أو تتجاهل اليوم الذي يهمّ.
 *
 * والتمييز يأتي **محسوباً من الخادم** (`needs_a_hand`) لا مستنتَجاً هنا:
 * تكرار المنطق في الواجهة يجعل شاشتين تختلفان على نفس الحقيقة.
 */
export default function ScanScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getScan(), {
    previewData: previewOr(fixtures.scan),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.scan.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.scan.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const instruments = data.instruments ?? [];

  return (
    <Screen
      testID="scan-screen"
      title={t.scan.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Banner testID="scan-summary" tone="info" title={data.summary_ar} body={t.scan.intro} />

      <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
        <View style={{ flex: 1 }}>
          <Field label={t.scan.scanned} value={String(data.scanned)} />
        </View>
        <View style={{ flex: 1 }}>
          <Field
            label={t.scan.faults}
            value={String(data.faults)}
            tone={data.faults > 0 ? 'negative' : 'primary'}
          />
        </View>
      </View>

      {instruments.length === 0 ? (
        <Vacancy
          testID="scan-empty"
          what={t.scan.noScanYet}
          why={t.scan.noScanWhy}
          tone="fault"
        />
      ) : (
        instruments.map((row: ScanInstrument) => (
          <Card
            key={row.symbol}
            testID={`scan-row-${row.symbol}`}
            title={row.symbol}
            accentBorder={row.needs_a_hand ? theme.colors.caution : undefined}
          >
            <StatusPill
              testID={`scan-pill-${row.symbol}`}
              tone={
                row.decision === 'TRADE'
                  ? 'positive'
                  : row.needs_a_hand
                    ? 'caution'
                    : 'neutral'
              }
              label={
                row.decision === 'TRADE'
                  ? t.scan.traded
                  : row.needs_a_hand
                    ? t.scan.needsAHand
                    : t.scan.normal
              }
            />
            {/* السبب كما كتبه الخادم. لا يُعاد صوغه هنا: إعادةُ الصوغ في
                الواجهة تُنتج جملةً لا يعرفها سجلّ التدقيق. */}
            <Text variant="caption" tone="secondary">
              {row.reason_ar ?? '—'}
            </Text>
            {row.stage !== null ? (
              <Text variant="micro" tone="tertiary">
                {t.scan.stage}: {row.stage}
              </Text>
            ) : null}
          </Card>
        ))
      )}
    </Screen>
  );
}
