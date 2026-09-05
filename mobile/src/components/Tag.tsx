import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { toneOf } from '@/theme/colors';
import { Text } from './Text';

/**
 * وسمُ نسبة الصفقة — **من اتّخذ قرارها**.
 *
 * الفصل ليس تصنيفاً إدارياً: نسبةُ خسارةٍ إداريةٍ إلى استراتيجيةٍ لم تتّخذ
 * قرارها تُفسد كلّ نسبة ربحٍ تُحسب بعدها. ولذلك يظهر الوسم على كلّ صفٍّ في
 * السجل، ولا يُترك للقارئ أن يستنتجه من السياق.
 *
 *   `STRATEGY`        صفقةٌ اتّخذتها استراتيجيةٌ معتمدة — تُحسب في أدائها.
 *   `ADMINISTRATIVE`  حركةٌ إدارية: تصفيةٌ يدوية أو تصحيح خطأ — **لا تُحسب**.
 *   `COMMISSIONING`   صفقةُ تشغيلٍ لاختبار المسار — **لا تُحسب**.
 *   `UNATTRIBUTED`    لم يُعرف من فتحها. ولا تُخمَّن نسبتُها.
 */
export type TradeKind = 'STRATEGY' | 'ADMINISTRATIVE' | 'COMMISSIONING' | 'UNATTRIBUTED';

const LABEL: Record<TradeKind, string> = {
  STRATEGY: 'استراتيجية',
  ADMINISTRATIVE: 'إغلاق إداري',
  COMMISSIONING: 'تشغيلية',
  UNATTRIBUTED: 'بلا نسبة',
};

/** هل تدخل في إحصاء أداء الاستراتيجية؟ */
export const countsTowardStrategy = (kind: TradeKind): boolean => kind === 'STRATEGY';

export interface TagProps {
  kind: TradeKind;
  testID?: string;
}

export function Tag({ kind, testID }: TagProps): React.JSX.Element {
  const theme = useTheme();
  // اللون يحمل «أتُحسب أم لا»، لا الربح ولا الخسارة.
  const tone = toneOf(
    theme.colors,
    kind === 'STRATEGY' ? 'accent' : kind === 'UNATTRIBUTED' ? 'caution' : 'neutral',
  );

  return (
    <View
      testID={testID}
      accessible={false}
      style={{
        alignSelf: 'flex-start',
        backgroundColor: tone.bg,
        borderRadius: theme.radii.sm,
        paddingVertical: theme.spacing.xxs,
        paddingHorizontal: theme.spacing.xs,
      }}
    >
      <Text variant="micro" style={{ color: tone.fg }}>
        {LABEL[kind]}
      </Text>
    </View>
  );
}

export const tagLabel = (kind: TradeKind): string => LABEL[kind];
