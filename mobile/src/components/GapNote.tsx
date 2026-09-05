import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * فجوةُ عقدٍ **معلَنة لا صامتة**.
 *
 * حين لا يصل حقلٌ من الخادم، أمامنا ثلاثة خيارات: أن نُخفي الكتلة، أو نملأها
 * بقيمةٍ مخترعة، أو **نقول إنّ الحقل غير موجودٍ بعد ولماذا**. الأوّل يجعل
 * الشاشة تبدو ناقصةً بلا سبب، والثاني كذب، والثالث هو ما يفعله هذا المكوّن.
 *
 * وهو بند التدقيق `E3`: الفجوة تُقال، ويُسمّى الحقل الناقص باسمه كي يُعرف ما
 * الذي يرفعها.
 */
export interface GapNoteProps {
  /** ما الذي لا يمكن عرضه. */
  title: string;
  /** لماذا — وأيّ حقلٍ يرفع الفجوة. */
  body: string;
  testID?: string;
}

export function GapNote({ title, body, testID }: GapNoteProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID={testID}
      accessible
      accessibilityLabel={`${title}. ${body}`}
      style={{
        borderWidth: 1,
        borderStyle: 'dashed',
        borderColor: theme.colors.borderStrong,
        borderRadius: theme.radii.md,
        padding: theme.spacing.md,
        gap: theme.spacing.xxs,
      }}
    >
      <Text variant="captionStrong" tone="caution">
        {title}
      </Text>
      <Text variant="caption" tone="secondary">
        {body}
      </Text>
    </View>
  );
}
