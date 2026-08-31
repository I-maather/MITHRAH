import React from 'react';
import { View, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * الحالة الصفرية المشروحة — **حالة، لا خطأ**.
 *
 * سُمّي `Vacancy` لا `EmptyState`: الاسم الثاني مأخوذ في `States.tsx` لمكوّنٍ
 * يعرض رسالةً واحدة. وتسميتُهما بالاسم نفسه جعلت `index.ts` يُصدّر الأول
 * ويحجب الثاني بصمت — والمترجم وحده أمسكها.
 *
 * ثلاث عشرة شاشة في هذا التطبيق تعرض فراغاً بلا تفسير، والفراغ هو ما ستراه
 * المالكة أكثر من غيره في الأسابيع الأولى: لا صفقات، لا مركز، لا تعارضات،
 * لا عيّنة كافية. وشاشةٌ فارغة تُقرأ «معطوب» بينما النظام سليم ويعمل.
 *
 * ## الحقول الثلاثة — كلّها مطلوبة إلا الأخير
 *
 *   `what`  ماذا يوجد الآن.            «لا مركز مفتوح.»
 *   `why`   لماذا — بلغة النظام.        «لا أدخل ببيانات ناقصة.»
 *   `next`  ما الذي سيغيّر هذا، ومتى.   «عند فتح السوق، الاثنين ٠٣:٠٠.»
 *
 * الحقل الثالث هو الذي يحوّل الفراغ من قلقٍ إلى معلومة. وحين لا يكون
 * معروفاً، يُترك — ولا يُخترع له نصّ مطمئن.
 *
 * ## لماذا لا أيقونة ولا رسم
 *
 * الرسوم اللطيفة في الحالات الفارغة تُخفّف وقع الفراغ، وهذا بالضبط ما لا
 * نريده: النظام مالي، والفراغ فيه معلومةٌ تُقرأ لا شعورٌ يُلطَّف.
 */
export interface VacancyProps {
  /** ماذا يوجد الآن — جملة واحدة مكتملة. */
  what: string;
  /** لماذا — بصوت النظام، لا بلغة المطوّرين. */
  why?: string;
  /** ما الذي سيغيّر هذا. يُترك حين لا يكون معروفاً. */
  next?: string;
  /** لهجة الإطار: محايدة، أو انتظارٌ مقصود، أو عطل. */
  tone?: 'neutral' | 'waiting' | 'fault';
  style?: ViewStyle;
  testID?: string;
}

export function Vacancy({
  what,
  why,
  next,
  tone = 'neutral',
  style,
  testID,
}: VacancyProps): React.JSX.Element {
  const theme = useTheme();

  const borderColor =
    tone === 'fault'
      ? theme.colors.negative
      : tone === 'waiting'
        ? theme.colors.caution
        : theme.colors.border;

  return (
    <View
      testID={testID}
      accessible
      accessibilityLabel={[what, why, next].filter(Boolean).join('، ')}
      style={{
        borderWidth: 1,
        borderStyle: 'dashed',
        borderColor,
        paddingVertical: theme.spacing.md,
        paddingHorizontal: theme.spacing.md,
        gap: theme.spacing.xs,
        ...style,
      }}
    >
      <Text variant="bodyStrong">{what}</Text>
      {why ? (
        <Text variant="caption" tone="secondary">
          {why}
        </Text>
      ) : null}
      {next ? (
        <Text variant="caption" tone="tertiary">
          {next}
        </Text>
      ) : null}
    </View>
  );
}
