import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * مسار اليوم — **أين توقّف، بالأرقام**.
 *
 * ## لماذا `DayPath` لا الاسم الإنجليزي المعتاد
 *
 * سُمّي أوّلَ مرّة باسم القمع الإنجليزي، فأسقطه حارسُ الأمن في
 * `security-boundary.test.ts`: الكلمة نفسها اسمُ خدمة نفقٍ عامة ممنوعة في
 * كلّ ملف. والحارس مُحقّ، وتضييقُه ليتّسع لاسم مكوّنٍ يُضعف حمايةً حقيقية
 * من أجل راحةِ تسمية. والاسم العربي هو اسم النموذج المعتمد أصلاً.
 *
 * هذا هو العنصر الوحيد المنقول من «غرفة الإشارة» إلى الاتجاه المعتمد، ومطوَّرٌ
 * عنها: خمس خطواتٍ صمّاء صارت خمس خطواتٍ **بأرقام**. وهو تنفيذٌ حرفيّ لقاعدة
 * نظام التشغيل: «أين توقف المسار بالأرقام» — لا «لا توجد فرصة اليوم».
 *
 * والفرق عمليّ لا لفظيّ: «صفر صفقات» لا تقول شيئاً، أمّا «فُحصت ٤ · مؤهّلة ٣ ·
 * إعداد ٠» فتقول إنّ التوقّف عند تكوين الإعداد لا عند التأهيل — ومن ذلك يُعرف
 * أهو غيابُ فرصةٍ أم عطلُ سياسة.
 *
 * ## القيم المجهولة
 *
 * `count` نصٌّ لا رقم عمداً: حين تنقطع القراءة تُكتب «—» ولا تُكتب صفر. والصفر
 * حقيقةٌ مقيسة، والشرطة اعترافٌ بالجهل — وخلطُهما هو ما بُني هذا النظام على
 * تجنّبه.
 *
 * ## `stopAt`
 *
 * فهرس الخطوة التي توقّف عندها المسار (صفريّ). `-1` يعني أنّ المسار اكتمل،
 * و`null` يعني أننا لا نعرف أين توقّف.
 */
export interface PathStep {
  /** اسم الخطوة: فُحصت · مؤهّلة · إعداد · إشارة · نُفّذت. */
  label: string;
  /** العدد كنصّ — أو «—» حين لا يُعرف. */
  count: string;
  /** هل بلغها المسار؟ */
  reached: boolean;
}

export interface DayPathProps {
  steps: readonly PathStep[];
  /** فهرس التوقّف. `-1` اكتمل · `null` غير معروف. */
  stopAt?: number | null;
  /** جملةٌ تقول ماذا يعني هذا التوقّف. */
  note: string;
  testID?: string;
}

export function DayPath({ steps, stopAt = null, note, testID }: DayPathProps): React.JSX.Element {
  const theme = useTheme();

  const spoken = steps.map((s) => `${s.label} ${s.count}`).join('، ');

  return (
    <View
      testID={testID}
      accessible
      accessibilityLabel={`مسار اليوم: ${spoken}. ${note}`}
      style={{
        backgroundColor: theme.colors.surfaceSunken,
        borderRadius: theme.radii.lg,
        padding: theme.spacing.md,
        gap: theme.spacing.sm,
      }}
    >
      <View style={{ flexDirection: 'row', gap: theme.spacing.xs }}>
        {steps.map((step, index) => (
          <View
            key={step.label}
            style={{
              flex: 1,
              height: 4,
              borderRadius: theme.radii.pill,
              backgroundColor: step.reached
                ? theme.colors.accent
                : index === stopAt
                  ? theme.colors.caution
                  : theme.colors.border,
            }}
          />
        ))}
      </View>

      <View style={{ flexDirection: 'row', gap: theme.spacing.xs }}>
        {steps.map((step, index) => (
          <View key={step.label} style={{ flex: 1, gap: theme.spacing.xxs }}>
            <Text
              variant="micro"
              tone={index === stopAt ? 'caution' : 'tertiary'}
              numberOfLines={1}
            >
              {step.label}
            </Text>
            <Text
              variant="captionStrong"
              tabular
              tone={index === stopAt ? 'caution' : 'primary'}
            >
              {step.count}
            </Text>
          </View>
        ))}
      </View>

      <Text variant="caption" tone="secondary">
        {note}
      </Text>
    </View>
  );
}
