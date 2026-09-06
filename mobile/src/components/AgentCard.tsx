import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { toneOf, type ToneName } from '@/theme/colors';
import { Glass } from './Glass';
import { Text } from './Text';

/**
 * «ما يفكر فيه الوكيل» — البطاقة التي تحمل القرار وسببه.
 *
 * موضعُها فوق المراكز عمداً: سؤال المالكة «هل أتدخّل؟» لا «كم عندي؟». وبطاقةٌ
 * تشرح صمت النظام هي الفراغ الذي وجده بحث المنافسين: **لا تطبيق واحد من
 * الثمانية عشر يعرض «لماذا لم أتداول»**.
 *
 * ## الشريط الجانبي
 *
 * `rail` خطٌّ ملوّن على حافة البداية يحمل حالة الوكيل قبل قراءة حرف. وهو
 * **الحدّ الوحيد الملوّن** في الشاشة، فلا يزاحمه شيء على الانتباه.
 *
 * ## الشرائح
 *
 * أرقامٌ صغيرة تسند الفقرة: «١٤٤ دورة» · «٤ أدوات» · «صفر إشارة». وكلٌّ منها
 * حقيقةٌ مقيسة لا زخرفة — وشريحةٌ بلا رقمٍ خلفها لا تُعرض.
 */
export interface AgentChip {
  label: string;
  tone?: ToneName;
}

export interface AgentCardProps {
  /**
   * عنوان الحالة — **اختياريّ**.
   *
   * كان إلزامياً، فكانت الشاشة تكتب الحكم مرّتين: في `Welcome` أعلاها وفي
   * هذا العنوان. ورُئي على الجهاز: «٥ مراكز مفتوحة.» مرّتين، وسببُها
   * ثلاثاً. فحين يقوله ما فوقها، لا تقوله هي.
   */
  title?: string;
  /** الفقرة التي تشرح، بأرقامها. */
  body: string;
  /** لون الشريط الجانبي — يحمل الحالة قبل القراءة. */
  tone?: ToneName;
  chips?: readonly AgentChip[];
  testID?: string;
}

export function AgentCard({
  title,
  body,
  tone = 'neutral',
  chips = [],
  testID,
}: AgentCardProps): React.JSX.Element {
  const theme = useTheme();
  const rail = toneOf(theme.colors, tone);

  return (
    /*
      `.ai` في النموذج المعتمد **زجاجٌ** لا بطاقةٌ صلبة، ومعه توهّجٌ بلون
      الشريط. وكانت هنا بطاقةً صلبةً بحدٍّ جانبيّ — فتُقرأ كبقيّة الصناديق،
      ولا شيء يقول إنها الجملةُ التي تشرح صمت النظام.
    */
    <Glass
      testID={testID}
      rail={rail.fg}
      glow={rail.fg}
      accessible
      // العنصرُ يُقرأ جملةً واحدة، فلا يُفرَّق نصُّه على قارئ الشاشة.
      // والعنوانُ اختياريّ، فلا يُنطَق «undefined» حين يقوله ما فوقها.
      accessibilityLabel={[title, body].filter(Boolean).join('. ')}
    >
      {title !== undefined ? <Text variant="bodyStrong">{title}</Text> : null}
      <Text variant="caption" tone="secondary">
        {body}
      </Text>
      {chips.length > 0 ? (
        <View
          accessible={false}
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: theme.spacing.xs,
            marginTop: theme.spacing.xxs,
          }}
        >
          {chips.map((chip) => {
            const c = toneOf(theme.colors, chip.tone ?? 'neutral');
            return (
              <View
                key={chip.label}
                style={{
                  backgroundColor: c.bg,
                  borderRadius: theme.radii.pill,
                  paddingVertical: theme.spacing.xxs,
                  paddingHorizontal: theme.spacing.sm,
                }}
              >
                <Text variant="micro" style={{ color: c.fg }}>
                  {chip.label}
                </Text>
              </View>
            );
          })}
        </View>
      ) : null}
    </Glass>
  );
}
