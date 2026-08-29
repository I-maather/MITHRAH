import React from 'react';
import { View } from 'react-native';

import { toneOf, useTheme, type ToneName } from '@/theme';
import { Text } from './Text';

interface StatusPillProps {
  label: string;
  tone?: ToneName;
  /** وصف مطوّل لـVoiceOver حين لا تكفي الكلمة الواحدة. */
  accessibilityLabel?: string;
  testID?: string;
}

/**
 * شارة حالة.
 *
 * اللون **ليس** الحامل الوحيد للمعنى: النص داخل الشارة يقول الحالة كاملة، فمن
 * لا يميّز الألوان يقرأ الحالة نفسها. (WCAG 1.4.1)
 */
export function StatusPill({
  label,
  tone = 'neutral',
  accessibilityLabel,
  testID,
}: StatusPillProps): React.JSX.Element {
  const theme = useTheme();
  const { fg, bg } = toneOf(theme.colors, tone);
  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={accessibilityLabel ?? label}
      testID={testID}
      style={{
        backgroundColor: bg,
        borderRadius: theme.radii.pill,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.xs,
        alignSelf: 'flex-start',
      }}
    >
      <Text variant="captionStrong" style={{ color: fg }}>
        {label}
      </Text>
    </View>
  );
}

interface DotProps {
  tone: ToneName;
}

/** نقطة صغيرة بجانب نصّ حالة. زينة فقط — لا تحمل معنى وحدها. */
export function ToneDot({ tone }: DotProps): React.JSX.Element {
  const theme = useTheme();
  const { fg } = toneOf(theme.colors, tone);
  return (
    <View
      accessible={false}
      importantForAccessibility="no"
      style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: fg }}
    />
  );
}
