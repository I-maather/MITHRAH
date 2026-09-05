import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * تحيّةٌ ثمّ **حكم**.
 *
 * أعلى شاشة «اليوم» في النموذج المعتمد ليس رقماً ولا مقياساً — بل جملةٌ تجيب
 * سؤال المالكة الفعليّ: «هل أتدخّل؟». والرقم يأتي بعدها لأنه يشرحها.
 *
 * والجملة تُكتب بصيغة المتكلّم لأن هذا صوت المنتج المكتوب أصلاً في `ar.ts`:
 * «لا أدخل إلا حين تكتمل شروطي كلها». وواجهةٌ صامتة فوق نصٍّ متكلّم تعارضٌ
 * يُشعَر به بعد أسبوع.
 *
 * `verdict` جملةٌ مكتملة بنقطتها. ولا تُختصر إلى كلمة: «لا شيء يحتاجكِ اليوم.»
 * تختلف عن «لا شيء» — الأولى جوابٌ والثانية فراغ.
 */
export interface WelcomeProps {
  /** التحيّة — تتغيّر بالوقت لا بالحالة. */
  greeting: string;
  /** الحكم — جملةٌ مكتملة تجيب «هل أتدخّل؟». */
  verdict: string;
  testID?: string;
}

export function Welcome({ greeting, verdict, testID }: WelcomeProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="header"
      accessibilityLabel={`${greeting}. ${verdict}`}
      style={{ gap: theme.spacing.xs }}
    >
      <Text variant="caption" tone="secondary">
        {greeting}
      </Text>
      <Text variant="title">{verdict}</Text>
    </View>
  );
}
