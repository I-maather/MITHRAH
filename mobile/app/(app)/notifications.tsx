import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  StatusPill,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatSince, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentNotification } from '@/utils/present';

/**
 * مركز الإشعارات.
 *
 * التفصيل يظهر **هنا فقط**، بعد المصادقة. شاشة القفل لا تحمل رقماً ولا اتجاهاً
 * ولا حجم مركز: نصّها ثابت لا يعتمد على محتوى الإشعار إطلاقاً، فلا يتسرّب رقم
 * عبرها ولو بالخطأ. القرار مُنفَّذ على الخادم قبل الإرسال (`FORBIDDEN_PAYLOAD_KEYS`).
 *
 * والإشعار **استشاري**: لا شيء في سلامة النظام يعتمد على وصوله. الوقف والهدف
 * لدى الوسيط، فلو صمت الهاتف أسبوعاً بقيت الحماية.
 */
export default function NotificationsScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getNotifications(), {
    previewData: previewOr(fixtures.notifications),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.notifications.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.notifications.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="notifications-screen"
      title={t.notifications.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Banner
        testID="lockscreen-privacy-banner"
        tone="info"
        title={t.notifications.privacyTitle}
        body={t.notifications.privacyBody}
      />

      <Banner
        testID="advisory-banner"
        tone="neutral"
        title={t.notifications.advisoryTitle}
        body={t.notifications.advisoryBody}
      />

      <Card testID="notifications-card">
        {data.notifications.length === 0 ? (
          <EmptyState testID="notifications-empty" message={t.notifications.empty} />
        ) : (
          data.notifications.map((notification, index) => {
            const presented = presentNotification(notification.type);
            return (
              <View
                key={`${notification.type}-${notification.created_utc}`}
                style={{ gap: theme.spacing.xs }}
              >
                {index > 0 ? <Divider /> : null}
                <View
                  accessible
                  accessibilityRole="text"
                  accessibilityLabel={`${presented.labelAr}. ${notification.in_app_detail_ar}. ${
                    notification.read ? t.notifications.read : t.notifications.unread
                  }. ${formatSince(notification.created_utc)}`}
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
                    <StatusPill label={presented.labelAr} tone={presented.tone} />
                    <Text variant="micro" tone="tertiary">
                      {formatSince(notification.created_utc)}
                    </Text>
                  </View>
                  <Text variant="body">{notification.in_app_detail_ar}</Text>
                  {!notification.read ? (
                    <Text variant="micro" tone="accent">
                      {t.notifications.unread}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })
        )}
      </Card>
    </Screen>
  );
}
