import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text, type TextTone } from './Text';

/**
 * ثلاثة أرقامٍ متجاورة — **ولا رقمَ رابعٌ يجمعها**.
 *
 * في شاشة السجل تحمل: استراتيجي · إداري · تشغيلي. وغيابُ «المحقَّق الكلّي» هنا
 * قرارٌ لا نسيان: جمعُ الثلاثة يعطي رقماً لا يقيس أداء استراتيجية — لأنّ
 * الإغلاق الإداري وصفقة التشغيل لم تتّخذهما استراتيجية. وهذا بند التدقيق
 * `E2` بنصّه.
 *
 * ويقبل عنصران أو ثلاثة أو أربعة؛ والاسم من الحالة الغالبة لا من قيدٍ صارم.
 */
export interface Tile {
  label: string;
  value: string;
  tone?: TextTone;
  /** يُنطق بدل القيمة حين يكون المكتوب رمزاً. */
  spoken?: string;
}

export interface TrioProps {
  tiles: readonly Tile[];
  testID?: string;
}

export function Trio({ tiles, testID }: TrioProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View testID={testID} style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
      {tiles.map((tile) => (
        <View
          key={tile.label}
          accessible
          accessibilityLabel={`${tile.label}: ${tile.spoken ?? tile.value}`}
          style={{
            flex: 1,
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.border,
            borderWidth: 1,
            borderRadius: theme.radii.md,
            paddingVertical: theme.spacing.md,
            paddingHorizontal: theme.spacing.sm,
            gap: theme.spacing.xxs,
          }}
        >
          <Text variant="micro" tone="tertiary" numberOfLines={1}>
            {tile.label}
          </Text>
          <Text variant="numeric" tabular tone={tile.tone ?? 'primary'}>
            {tile.value}
          </Text>
        </View>
      ))}
    </View>
  );
}
