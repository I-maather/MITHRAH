import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

interface RiskMeterProps {
  label: string;
  /** المستهلَك — نص من الخادم كما هو. */
  usedLabel: string | null;
  /** المتبقي — نص من الخادم كما هو. */
  remainingLabel: string | null;
  /**
   * كسر الاستهلاك 0..1 للرسم فقط. `null` يعني **لا رسم** — لا يُخمَّن شريط.
   */
  ratio: number | null;
  testID?: string;
}

/**
 * مقياس المخاطرة.
 *
 * الشريط **زينة للرقم لا بديل عنه**: النص يحمل القيمتين كاملتين، وVoiceOver
 * يقرأهما. إذا لم يرسل الخادم كسراً، لا يُرسم شريط ولا يُقدَّر — الفراغ أصدق
 * من عمود بطول مُختلَق.
 */
export function RiskMeter({
  label,
  usedLabel,
  remainingLabel,
  ratio,
  testID,
}: RiskMeterProps): React.JSX.Element {
  const theme = useTheme();
  const clamped = ratio === null ? null : Math.max(0, Math.min(1, ratio));

  const tone =
    clamped === null
      ? theme.colors.textTertiary
      : clamped >= 0.85
        ? theme.colors.negative
        : clamped >= 0.6
          ? theme.colors.caution
          : theme.colors.accent;

  const spoken = `${label}. المستهلك ${usedLabel ?? 'غير متاح'}. المتبقي ${
    remainingLabel ?? 'غير متاح'
  }.`;

  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={spoken}
      accessibilityValue={clamped === null ? undefined : { min: 0, max: 100, now: Math.round(clamped * 100) }}
      style={{ gap: theme.spacing.sm }}
    >
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
        <Text variant="captionStrong" tabular>
          {usedLabel ?? '—'}
        </Text>
      </View>

      {clamped === null ? null : (
        <View
          accessible={false}
          importantForAccessibility="no"
          style={{
            height: 6,
            borderRadius: 3,
            backgroundColor: theme.colors.surfaceSunken,
            overflow: 'hidden',
            flexDirection: 'row',
          }}
        >
          <View
            style={{
              width: `${clamped * 100}%`,
              backgroundColor: tone,
              borderRadius: 3,
            }}
          />
        </View>
      )}

      <Text variant="micro" tone="tertiary">
        {`المتبقي: ${remainingLabel ?? 'غير متاح'}`}
      </Text>
    </View>
  );
}
