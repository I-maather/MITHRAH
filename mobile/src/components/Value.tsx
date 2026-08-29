import React from 'react';
import { View } from 'react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme';
import type { TextTone } from './Text';
import { Text } from './Text';

interface FieldProps {
  label: string;
  /**
   * القيمة كما وصلت من الخادم. `null` أو `undefined` تعني **لم تصل**،
   * فتُعرض «غير متاح» — ولا تُخترع قيمة ولا صفر ولا شرطة مضلِّلة.
   */
  value: string | number | null | undefined;
  tone?: TextTone;
  /** توضيح صغير تحت القيمة. */
  hint?: string;
  /** نطق بديل لـVoiceOver. */
  accessibilityValue?: string;
  testID?: string;
  large?: boolean;
}

/**
 * صف «تسمية ← قيمة».
 *
 * القاعدة الوحيدة هنا: **لا قيمة مُختلَقة**. غياب البيانات يُقال صراحةً، لأن
 * رقماً افتراضياً على شاشة مالية أسوأ من فراغ.
 */
export function Field({
  label,
  value,
  tone = 'primary',
  hint,
  accessibilityValue,
  testID,
  large = false,
}: FieldProps): React.JSX.Element {
  const theme = useTheme();
  const missing = value === null || value === undefined || value === '';
  const shown = missing ? t.common.unavailable : String(value);

  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={`${label}: ${accessibilityValue ?? shown}`}
      testID={testID}
      style={{
        flexDirection: 'row',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: theme.spacing.md,
        minHeight: 28,
      }}
    >
      <View style={{ flexShrink: 1, gap: 2 }}>
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
        {hint !== undefined ? (
          <Text variant="micro" tone="tertiary">
            {hint}
          </Text>
        ) : null}
      </View>
      <Text
        variant={large ? 'numeric' : 'bodyStrong'}
        tone={missing ? 'tertiary' : tone}
        align="end"
        tabular
        style={{ flexShrink: 0, maxWidth: '60%' }}
      >
        {shown}
      </Text>
    </View>
  );
}

interface MetricProps {
  label: string;
  value: string | number | null | undefined;
  tone?: TextTone;
  caption?: string;
  testID?: string;
}

/** رقم بارز — يُستعمل مرة أو مرتين في الشاشة لا أكثر. */
export function Metric({
  label,
  value,
  tone = 'primary',
  caption,
  testID,
}: MetricProps): React.JSX.Element {
  const theme = useTheme();
  const missing = value === null || value === undefined || value === '';
  const shown = missing ? t.common.unavailable : String(value);
  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={`${label}: ${shown}`}
      testID={testID}
      style={{ gap: theme.spacing.xxs, flex: 1 }}
    >
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Text variant="numericLarge" tone={missing ? 'tertiary' : tone} tabular>
        {shown}
      </Text>
      {caption !== undefined ? (
        <Text variant="micro" tone="tertiary">
          {caption}
        </Text>
      ) : null}
    </View>
  );
}
