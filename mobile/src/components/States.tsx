import React from 'react';
import { ActivityIndicator, View } from 'react-native';

import { ApiError } from '@/api/client';
import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { Banner } from './Banner';
import { Button } from './Button';
import { Text } from './Text';

/** حالة الانتظار. */
export function LoadingState(): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID="loading-state"
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={t.common.loading}
      style={{ paddingVertical: theme.spacing.huge, alignItems: 'center', gap: theme.spacing.md }}
    >
      <ActivityIndicator color={theme.colors.accent} />
      <Text variant="caption" tone="secondary">
        {t.common.loading}
      </Text>
    </View>
  );
}

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
}

/**
 * حالة الخطأ.
 *
 * كل صنف خطأ يقول ما حدث بلغة صريحة. لا «حدث خطأ ما»: على شاشة مالية، الغموض
 * يدفع إلى تخمين خاطئ.
 */
export function ErrorState({ error, onRetry }: ErrorStateProps): React.JSX.Element {
  const theme = useTheme();
  const { title, body, tone } = describe(error);
  return (
    <View testID="error-state" style={{ gap: theme.spacing.lg }}>
      <Banner title={title} body={body} tone={tone} />
      {onRetry !== undefined ? (
        <Button
          label={t.common.retry}
          kind="quiet"
          tone="neutral"
          accessibilityLabel={t.common.retry}
          testID="retry-button"
          onPress={onRetry}
        />
      ) : null}
    </View>
  );
}

function describe(error: unknown): {
  title: string;
  body: string;
  tone: 'negative' | 'caution';
} {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case 'OFFLINE':
        return { title: t.errors.offlineTitle, body: t.errors.offlineBody, tone: 'caution' };
      case 'UNAUTHORISED':
        return {
          title: t.errors.unauthorisedTitle,
          body: t.errors.unauthorisedBody,
          tone: 'negative',
        };
      case 'UNTRUSTED_ENDPOINT':
        return { title: t.errors.untrustedTitle, body: t.errors.untrustedBody, tone: 'negative' };
      case 'MALFORMED':
        return { title: t.errors.malformedTitle, body: t.errors.malformedBody, tone: 'negative' };
      case 'FORBIDDEN':
      case 'SERVER':
      default:
        return { title: t.errors.serverTitle, body: error.messageAr, tone: 'negative' };
    }
  }
  return { title: t.errors.serverTitle, body: t.errors.offlineBody, tone: 'negative' };
}

interface EmptyStateProps {
  message: string;
  testID?: string;
}

/** لا بيانات — وهذا يُقال، ولا يُملأ الفراغ برقم. */
export function EmptyState({ message, testID }: EmptyStateProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID={testID ?? 'empty-state'}
      accessible
      accessibilityRole="text"
      accessibilityLabel={message}
      style={{ paddingVertical: theme.spacing.xxl, alignItems: 'center' }}
    >
      <Text variant="body" tone="tertiary" align="center">
        {message}
      </Text>
    </View>
  );
}
