import React from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme';
import { Glass } from './Glass';
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
  /**
   * **مادّةُ البطاقة.**
   *
   * `solid` هي `.card` في النموذج: `night-800` بحدٍّ واستدارة 18.
   * `glass` هي `.glass`: أربعُ طبقاتٍ واستدارة 26 — وهي مادّةُ البطاقتين
   * الحاملتين في شاشة «اليوم» (المحفظة المخصَّصة، وما يفكر فيه الوكيل).
   */
  variant?: 'solid' | 'glass';
  /** لون التوهّج خلف الزجاج — `.ai:after` في النموذج. */
  glow?: string;
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
  variant = 'solid',
  glow,
}: CardProps): React.JSX.Element {
  const theme = useTheme();

  const head =
    title !== undefined ? (
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
    ) : null;

  if (variant === 'glass') {
    return (
      <Glass testID={testID} glow={glow} style={style}>
        {head}
        {children}
      </Glass>
    );
  }

  return (
    <View
      testID={testID}
      accessible={false}
      style={[
        {
          backgroundColor: theme.colors.surface,
          borderColor: accentBorder ?? theme.colors.border,
          borderWidth: accentBorder === undefined ? 1 : 1.5,
          // استدارةُ `.card` في النموذج — كانت `lg = 14`، فتُقرأ «مقربعة».
          borderRadius: theme.radii.card,
          padding: theme.spacing.lg,
          // فراغُ النموذج بين صفوف البطاقة أضيق — 8 لا 12.
          gap: theme.spacing.sm,
        },
        style,
      ]}
    >
      {head}
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
