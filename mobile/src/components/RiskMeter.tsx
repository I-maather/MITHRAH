import React from 'react';
import { View } from 'react-native';

import { useTheme } from '@/theme';
import { AnimatedNumber } from './AnimatedNumber';
import { Text } from './Text';

interface RiskMeterProps {
  label: string;
  usedLabel: string | null;
  remainingLabel: string | null;
  /** المتبقّي رقماً، للعدّ المتدرّج. `null` ⇒ يُعرض النص كما هو بلا حركة. */
  remainingValue?: number | null;
  /** كسر الاستهلاك 0..1 للرسم فقط. `null` يعني **لا رسم** — لا يُخمَّن شريط. */
  ratio: number | null;
  testID?: string;
}

/** ثلاث درجات، ولكلٍّ منها **كلمة** لا لون فقط. */
function band(r: number): { word: string; step: 0 | 1 | 2 } {
  if (r >= 0.85) return { word: 'قريب جداً من الحدّ', step: 2 };
  if (r >= 0.6) return { word: 'اقترب من الحدّ', step: 1 };
  return { word: 'ضمن المدى', step: 0 };
}

/**
 * مقياس المخاطرة — «الحدّ».
 *
 * ## ما تغيّر، ولماذا
 *
 * **١. المتبقّي هو البطل.** كان بحجم 11pt بلون ثانوي، والمستهلَك أكبر منه —
 * أي أن الشاشة كانت تبرز ما أنفقتِه لا ما بقي لك. وبحثك يقول إن الرقم الكبير
 * ليس الرصيد؛ وهنا الرقم الكبير هو **ما تبقّى من مخاطرة اليوم**.
 *
 * **٢. الثخانة تحمل التصعيد لا اللون.** كان الشريط يصعّد بلونٍ وحده
 * (0.6 ⇒ تحذير، 0.85 ⇒ خطر) و`importantForAccessibility="no"` يخفيه عن
 * قارئ الشاشة. فمن لا يميّز الألوان — أو ينظر في الشمس — لا يرى شيئاً.
 * الآن: 2px ⇒ 3px ⇒ 5px، **ومعها كلمة منطوقة ومكتوبة**.
 *
 * **٣. اللون آخر طبقة لا أولها.** يبقى رمادياً حتى 85٪، ثم يظهر الأحمر —
 * فيُرى بندرته. وهذا هو تطبيق قاعدة النظام: اللون معلومة لا زينة.
 */
export function RiskMeter({
  label,
  usedLabel,
  remainingLabel,
  remainingValue = null,
  ratio,
  testID,
}: RiskMeterProps): React.JSX.Element {
  const theme = useTheme();
  const clamped = ratio === null ? null : Math.max(0, Math.min(1, ratio));
  const b = clamped === null ? null : band(clamped);

  const HEIGHTS = [2, 3, 5] as const;
  const height = b === null ? 2 : HEIGHTS[b.step];
  const fill =
    b === null
      ? theme.colors.textTertiary
      : b.step === 2
        ? theme.colors.negative
        : theme.colors.textSecondary;

  const spoken =
    `${label}. المتبقّي ${remainingLabel ?? 'غير متاح'}. ` +
    `المستهلَك ${usedLabel ?? 'غير متاح'}.` +
    (b === null ? '' : ` ${b.word}، ${Math.round(clamped! * 100)} بالمئة.`);

  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={spoken}
      accessibilityValue={
        clamped === null ? undefined : { min: 0, max: 100, now: Math.round(clamped * 100) }
      }
      style={{ gap: theme.spacing.sm }}
    >
      <Text variant="caption" tone="secondary">
        {label}
      </Text>

      {remainingValue !== null ? (
        <AnimatedNumber value={remainingValue} decimals={2} unit="دولار" variant="numericLarge" />
      ) : (
        <Text variant="numericLarge" tabular>
          {remainingLabel ?? '—'}
        </Text>
      )}

      {clamped === null ? null : (
        <View
          accessible={false}
          importantForAccessibility="no"
          style={{
            height,
            borderRadius: height / 2,
            backgroundColor: theme.colors.surfaceSunken,
            overflow: 'hidden',
            flexDirection: 'row',
          }}
        >
          <View
            style={{ width: `${clamped * 100}%`, backgroundColor: fill, borderRadius: height / 2 }}
          />
        </View>
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: theme.spacing.sm }}>
        <Text variant="micro" tone="secondary" testID="risk-band">
          {b === null ? 'النسبة غير متاحة' : `${b.word} · ${Math.round(clamped! * 100)}٪`}
        </Text>
        <Text variant="micro" tone="tertiary" tabular>
          {`المستهلَك ${usedLabel ?? '—'}`}
        </Text>
      </View>
    </View>
  );
}
