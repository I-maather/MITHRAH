import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Card,
  Divider,
  EmptyState,
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
      {data.trades.length === 0 ? (
        <EmptyState testID="history-empty" message={t.history.empty} />
      ) : (
        data.trades.map((trade) => (
          <Card key={trade.id} testID={`trade-${trade.id}`}>
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
