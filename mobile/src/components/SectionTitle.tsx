import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text, type TextTone } from './Text';

/**
 * عنوانُ قسمٍ ومعه **حاشيةٌ على الطرف الآخر**.
 *
 * الحاشية ليست زخرفة: هي التي تقول «آخر مزامنة الآن» أو «من السقف» أو «٤
 * سبتمبر» — أي **مدى صلاحية ما تحته**. وقسمٌ بلا هذا يترك القارئ يظنّ أنّ ما
 * يراه لحظيّ وقد يكون عمره ساعة.
 *
 * ويظهر العنوان لـVoiceOver عنواناً، والحاشية نصّاً بعده — لا يُقرآن ككتلةٍ
 * واحدة كي يمكن القفز بين الأقسام.
 */
export interface SectionTitleProps {
  title: string;
  /** حاشية الطرف الآخر — صلاحية، أو مصدر، أو حدّ. */
  note?: string;
  noteTone?: TextTone;
  testID?: string;
}

export function SectionTitle({
  title,
  note,
  noteTone = 'tertiary',
  testID,
}: SectionTitleProps): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID={testID}
      style={{
        flexDirection: 'row',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        gap: theme.spacing.sm,
        marginTop: theme.spacing.xs,
      }}
    >
      <Text variant="heading" accessibilityRole="header">
        {title}
      </Text>
      {note !== undefined ? (
        <Text variant="caption" tone={noteTone}>
          {note}
        </Text>
      ) : null}
    </View>
  );
}
