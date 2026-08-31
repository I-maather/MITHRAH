import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
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

/**
 * خط التدقيق.
 *
 * القيود تُعرض بترتيب الخادم و**بنصّها**، بما فيها الإخفاقات. الإخفاق المعروض
 * أنفع من سجل نظيف: محاولة تسجيل مرفوضة أو رمز تجديد مُعاد استعماله هي أول ما
 * يجب أن تراه المالكة.
 */
export default function AuditScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getAudit(), {
    previewData: previewOr(fixtures.audit),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.audit.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.audit.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="audit-screen"
      title={t.audit.title}
      subtitle={`${data.entries.length}`}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Card testID="audit-card">
        {data.entries.length === 0 ? (
          <Vacancy testID="audit-empty" what={t.audit.empty} why={t.audit.emptyWhy} />
        ) : (
          [...data.entries].reverse().map((entry, index) => (
            <View key={`${entry.at_utc}-${entry.action}-${index}`} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <View
                accessible
                accessibilityRole="text"
                accessibilityLabel={`${entry.action}. ${
                  entry.success ? t.audit.success : t.audit.failure
                }. ${entry.detail_ar}. ${formatInstant(entry.at_utc)}`}
                style={{ gap: theme.spacing.xs }}
              >
                <View
                  style={{
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: theme.spacing.sm,
                  }}
                >
                  <Text variant="bodyStrong" style={{ flex: 1 }}>
                    {entry.action}
                  </Text>
                  <StatusPill
                    label={entry.success ? t.audit.success : t.audit.failure}
                    tone={entry.success ? 'positive' : 'negative'}
                  />
                </View>
                <Text variant="caption" tone="secondary">
                  {entry.detail_ar}
                </Text>
                <Field label="الوقت" value={formatInstant(entry.at_utc)} />
                <Field label={t.audit.device} value={entry.device_id} />
              </View>
            </View>
          ))
        )}
      </Card>
    </Screen>
  );
}
