import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  Vacancy,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  StatusPill,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentPnlTone } from '@/utils/present';

/**
 * سجل الصفقات.
 *
 * كل صفقة تحمل **سبب خروجها** لا نتيجتها وحدها: «ربح» بلا سبب لا تُعلّم شيئاً،
 * و«وقف» مع سببه تُعلّم.
 */
export default function HistoryScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getTrades(), {
    previewData: previewOr(fixtures.trades),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.history.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.history.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="history-screen"
      title={t.history.title}
      subtitle={`${data.trades.length}`}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {/*
        **قائمةٌ فارغة لا تُعرَض «لا صفقات» قبل أن نعرف أننا قرأنا.**

        كان الخادم يُعيد `[]` ثابتة بتعليقٍ يقول «قائمة فارغة صادقة: لم
        يُرسَل أمرٌ قط» — وصارت كاذبةً يوم أُغلقت أوّل صفقتين بمحقَّقٍ
        ‎−0.35‎ دولار. فالشاشة تسأل `sync.ok` أوّلاً.
      */}
      {!data.sync.ok || data.unavailable ? (
        <Banner
          testID="history-sync-error"
          tone="negative"
          title="تعذّرت قراءة الصفقات"
          body={`${data.sync.error_ar} — القائمة الفارغة هنا ليست «لا صفقات».`}
        />
      ) : data.sync.stale ? (
        <Banner
          testID="history-sync-stale"
          tone="caution"
          title="قراءةٌ قديمة"
          body={`آخر مزامنة قبل ${data.sync.age_seconds ?? '—'} ثانية.`}
        />
      ) : null}

      {data.sync.ok && !data.unavailable && data.realised_pnl_total !== null ? (
        <Card testID="history-total-card" title="المحقَّق الكلي">
          <Field label="مجموع الصفقات المغلقة" value={data.realised_pnl_total} large />
        </Card>
      ) : null}

      {!data.sync.ok || data.unavailable ? null : data.trades.length === 0 ? (
        <Vacancy
          testID="history-empty"
          what={t.history.empty}
          why={t.history.emptyWhy}
          next={t.history.emptyNext}
        />
      ) : (
        data.trades.map((trade) => (
          <Card key={trade.id ?? `${trade.instrument}-${trade.closed_utc}`} testID={`trade-${trade.id ?? 'x'}`}>
            <View
              style={{
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: theme.spacing.sm,
              }}
              accessible
              accessibilityRole="text"
              accessibilityLabel={`${trade.instrument_ar ?? trade.instrument}. ${
                trade.direction_ar
              }. ${trade.outcome_ar ?? ''}. ${trade.realised_pnl ?? ''}`}
            >
              <Text variant="bodyStrong" style={{ flex: 1 }}>
                {trade.instrument_ar ?? trade.instrument}
              </Text>
              {trade.kind === 'COMMISSIONING' ? (
                <StatusPill label="تشغيل" tone="neutral" />
              ) : null}
              {trade.outcome_ar !== null ? (
                <StatusPill
                  label={trade.outcome_ar}
                  tone={
                    trade.realised_pnl_sign === 'POSITIVE'
                      ? 'positive'
                      : trade.realised_pnl_sign === 'NEGATIVE'
                        ? 'negative'
                        : 'neutral'
                  }
                />
              ) : null}
            </View>

            <Divider />

            <Field label="الاتجاه" value={trade.direction_ar} />
            <Field label={t.history.opened} value={formatInstant(trade.opened_utc)} />
            <Field label={t.history.closed} value={formatInstant(trade.closed_utc)} />
            <Field label="سعر الدخول" value={trade.entry_price} />
            <Field label="سعر الخروج" value={trade.exit_price} />
            <Field
              label={t.history.result}
              value={trade.realised_pnl}
              tone={presentPnlTone(trade.realised_pnl_sign)}
              large
            />
            <Field label="الاستراتيجية" value={trade.strategy_ar} />
            <Field label={t.history.exitReason} value={trade.exit_reason_ar} />
          </Card>
        ))
      )}
    </Screen>
  );
}
