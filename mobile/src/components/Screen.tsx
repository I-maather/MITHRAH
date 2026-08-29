import React from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSession } from '@/auth/SessionProvider';
import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { PreviewBanner } from './Banner';
import { Text } from './Text';

interface ScreenProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  /** يعرض شريط «معاينة / Preview» فوق كل شيء. */
  preview?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  testID?: string;
}

/**
 * غلاف الشاشة.
 *
 * يتولّى ثلاثة أشياء لا تُترك للشاشات:
 *   1. المسافات الآمنة والتمرير.
 *   2. تسجيل التفاعل كي يُعاد ضبط مؤقّت القفل التلقائي مع كل لمسة.
 *   3. إظهار وسم المعاينة إن كانت البيانات من `src/fixtures/`.
 */
export function Screen({
  title,
  subtitle,
  children,
  preview = false,
  onRefresh,
  refreshing = false,
  testID,
}: ScreenProps): React.JSX.Element {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { registerActivity } = useSession();

  return (
    <ScrollView
      testID={testID}
      style={{ flex: 1, backgroundColor: theme.colors.background }}
      contentContainerStyle={{
        padding: theme.spacing.lg,
        paddingBottom: insets.bottom + theme.spacing.huge,
        gap: theme.spacing.lg,
      }}
      onScrollBeginDrag={registerActivity}
      onTouchStart={registerActivity}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh === undefined ? undefined : (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              registerActivity();
              onRefresh();
            }}
            tintColor={theme.colors.textSecondary}
            accessibilityLabel={t.common.refresh}
          />
        )
      }
    >
      <View style={{ gap: theme.spacing.xxs }}>
        <Text variant="display" accessibilityRole="header">
          {title}
        </Text>
        {subtitle !== undefined ? (
          <Text variant="caption" tone="secondary">
            {subtitle}
          </Text>
        ) : null}
      </View>

      {preview ? <PreviewBanner /> : null}

      {children}
    </ScrollView>
  );
}
