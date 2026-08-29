import React from 'react';
import { View } from 'react-native';

import { t } from '@/i18n';
import { toneOf, useTheme, type ToneName } from '@/theme';
import { Text } from './Text';

interface BannerProps {
  title: string;
  body?: string;
  tone?: ToneName;
  testID?: string;
}

/** شريط تنبيه أعلى الشاشة. */
export function Banner({
  title,
  body,
  tone = 'caution',
  testID,
}: BannerProps): React.JSX.Element {
  const theme = useTheme();
  const { fg, bg } = toneOf(theme.colors, tone);
  return (
    <View
      accessible
      accessibilityRole="alert"
      accessibilityLabel={body === undefined ? title : `${title}. ${body}`}
      testID={testID}
      style={{
        backgroundColor: bg,
        borderRightWidth: 3,
        borderRightColor: fg,
        borderRadius: theme.radii.md,
        paddingVertical: theme.spacing.md,
        paddingHorizontal: theme.spacing.lg,
        gap: theme.spacing.xxs,
      }}
    >
      <Text variant="captionStrong" style={{ color: fg }}>
        {title}
      </Text>
      {body !== undefined ? (
        <Text variant="caption" tone="secondary">
          {body}
        </Text>
      ) : null}
    </View>
  );
}

/**
 * وسم المعاينة.
 *
 * كل شاشة تعرض بيانات من `src/fixtures/` **يجب** أن تحمل هذا الشريط. وجوده
 * شرط في `__tests__/preview-fixtures.test.tsx`، كي لا تُقرأ بيانات تطوير على
 * أنها حالة حقيقية.
 */
export function PreviewBanner(): React.JSX.Element {
  return (
    <Banner
      testID="preview-banner"
      tone="info"
      title={t.common.previewBadge}
      body={t.common.previewNotice}
    />
  );
}

interface StaleBannerProps {
  sinceLabel: string;
}

/** شريط «الحالة قديمة» — يظهر حين يتجاوز عمر آخر تحديث الحد. */
export function StaleBanner({ sinceLabel }: StaleBannerProps): React.JSX.Element {
  return (
    <Banner
      testID="stale-banner"
      tone="caution"
      title={t.errors.staleTitle}
      body={`${t.errors.staleBody} ${sinceLabel}.`}
    />
  );
}

/** شريط انقطاع الشبكة. */
export function OfflineBanner(): React.JSX.Element {
  return (
    <Banner
      testID="offline-banner"
      tone="negative"
      title={t.errors.offlineTitle}
      body={t.errors.offlineBody}
    />
  );
}
