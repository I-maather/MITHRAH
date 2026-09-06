import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { fontFamilies } from '@/theme/tokens';
import { Text } from './Text';

/**
 * مسارُ اليوم — «قمع اليوم» في النموذج المعتمد.
 *
 * خمسُ خطواتٍ بأرقامها، وأين توقّف المسار. تنفيذٌ حرفيّ لقاعدةِ «أين توقف
 * المسار بالأرقام»: خطواتٌ صمّاء بلا أرقامٍ لا تقول شيئاً.
 *
 * ## الألوان تحمل المعنى
 *
 * كانت الأشرطةُ رماديّةً كلَّها، فلا يُعرف ما بلغ ممّا لم يبلغ. وفي النموذج:
 *
 *   · ما بلغ        → الجمر.
 *   · موضعُ التوقّف → الكثيب، ومعه اسمُه ورقمُه.
 *   · ما لم يبلغ    → حدُّ الليل.
 *
 * ## و«—» ليست صفراً
 *
 * `count` نصٌّ لا رقم: «—» تعني «لم يُفحَص بعد»، و«0» تعني «فُحص فلم يوجد».
 * وخلطُهما يجعل يوماً لم يبدأ يبدو يوماً بلا فرص.
 */
export interface DayStep {
  label: string;
  count: string;
  reached: boolean;
}

/** الاسمُ القديم — يبقى تصديرُه فلا ينكسر ما يستورده. */
export type PathStep = DayStep;

export interface DayPathProps {
  steps: readonly DayStep[];
  /** موضعُ التوقّف — `null` إن لم يُعرف. */
  stopAt?: number | null;
  note?: string | null;
  testID?: string;
}

export function DayPath({ steps, stopAt = null, note, testID }: DayPathProps): React.JSX.Element {
  const theme = useTheme();

  return (
    <View
      testID={testID}
      accessible
      /*
        **يُنطق مساراً لا أشرطة.** قارئُ الشاشة لا يرى اللون، فلو قُرئ كلُّ
        شريطٍ وحده لسمعت المالكةُ خمسَ شظايا بلا معنى. والجملةُ الواحدة
        تقول الخطوةَ ورقمَها، و«—» تُنطق «لم يُفحَص بعد» لا صفراً.
      */
      accessibilityLabel={[
        steps
          .map((step) => `${step.label} ${step.count}`)
          .join('، '),
        note ?? '',
      ]
        .filter((part) => part !== '')
        .join('. ')}
      style={{
        backgroundColor: theme.colors.surfaceSunken,
        borderWidth: 1,
        borderColor: theme.colors.border,
        borderRadius: theme.radii.card,
        padding: 14,
        gap: 9,
      }}
    >
      <View style={{ flexDirection: 'row', gap: 5 }}>
        {steps.map((step, i) => (
          <View
            key={`bar-${step.label}`}
            style={{
              flex: 1,
              height: 5,
              borderRadius: 4,
              backgroundColor: step.reached
                ? theme.colors.accent
                : i === stopAt
                  ? theme.colors.caution
                  : theme.colors.border,
            }}
          />
        ))}
      </View>

      <View style={{ flexDirection: 'row', gap: 5 }}>
        {steps.map((step, i) => {
          const stopped = i === stopAt;
          return (
            <View key={`lab-${step.label}`} accessible={false} style={{ flex: 1, gap: 3 }}>
              <Text
                variant="micro"
                numberOfLines={1}
                style={{
                  fontSize: 9.5,
                  color: stopped ? theme.colors.caution : theme.colors.textSecondary,
                }}
              >
                {step.label}
              </Text>
              <Text
                variant="micro"
                tabular
                style={{
                  fontSize: 13,
                  fontFamily: fontFamilies.numeric['700'],
                  color: stopped
                    ? theme.colors.caution
                    : step.reached
                      ? theme.colors.textPrimary
                      : theme.colors.textTertiary,
                }}
              >
                {step.count}
              </Text>
            </View>
          );
        })}
      </View>

      {note !== null && note !== undefined && note !== '' ? (
        <>
          <View style={{ height: 1, backgroundColor: theme.colors.border, marginTop: 2 }} />
          <Text
            variant="caption"
            style={{ fontSize: 10, lineHeight: 17, color: theme.colors.textSecondary }}
          >
            {note}
          </Text>
        </>
      ) : null}
    </View>
  );
}
