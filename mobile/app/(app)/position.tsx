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
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentPnlTone } from '@/utils/present';

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

  return (
    <Screen
      testID="position-screen"
      title={t.position.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {!data.has_position ? (
        <EmptyState testID="position-empty" message={t.position.none} />
      ) : (
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

      <Banner
        testID="position-readonly-banner"
        tone="neutral"
        title={t.common.readOnly}
        body={t.position.cannotModify}
      />
    </Screen>
  );
}
