import React from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

interface CardProps {
  children: React.ReactNode;
  /** عنوان القسم — يُعلَن لـVoiceOver بوصفه عنواناً. */
  title?: string;
  /** سطر توضيحي تحت العنوان. */
  subtitle?: string;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  /** لون حدّ دلالي عند الحاجة (مثلاً مركز مفتوح، قاطع مُفعَّل). */
  accentBorder?: string;
}

/**
 * بطاقة. الفصل بالحدود لا بالظل — أهدأ على العين وأوضح في الوضع الداكن.
 */
export function Card({
  children,
  title,
  subtitle,
  style,
  testID,
  accentBorder,
}: CardProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID={testID}
      accessible={false}
      style={[
        {
          backgroundColor: theme.colors.surface,
          borderColor: accentBorder ?? theme.colors.border,
          borderWidth: accentBorder === undefined ? 1 : 1.5,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.lg,
          gap: theme.spacing.md,
        },
        style,
      ]}
    >
      {title !== undefined ? (
        <View style={{ gap: theme.spacing.xxs }}>
          <Text variant="heading" accessibilityRole="header">
            {title}
          </Text>
          {subtitle !== undefined ? (
            <Text variant="caption" tone="secondary">
              {subtitle}
            </Text>
          ) : null}
        </View>
      ) : null}
      {children}
    </View>
  );
}

/** فاصل رفيع بين صفوف البطاقة. */
export function Divider(): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      accessible={false}
      importantForAccessibility="no"
      style={{ height: 1, backgroundColor: theme.colors.border }}
    />
  );
}
