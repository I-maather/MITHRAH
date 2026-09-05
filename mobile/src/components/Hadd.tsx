import React from 'react';
import { View, type ViewStyle } from 'react-native';

import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * «الحدّ» — العنصر التوقيعي.
 *
 * أداة قياس واحدة تُقرأ في كل شاشة: خطٌّ رفيع هو المدى، وجزءٌ معتم هو
 * المستهلَك، وعلامةٌ واحدة هي موضعك الآن، وعلاماتٌ باهتة هي العتبات.
 *
 * ## لماذا عنصر واحد لا ستة
 *
 * النظام يقيس ستة أشياء مختلفة — المخاطرة، والمسافة إلى القاطع، واكتمال
 * البيانات، والعائد إلى المخاطرة، وموضع السعر بين الوقف والهدف، وصدق العيّنة.
 * وكلٌّ منها «قيمة داخل مدى بعتبات». حين تُرسم بشكل واحد، تتعلّمينه مرّة
 * وتقرئينه في كل موضع؛ وحين تُرسم بستة أشكال، تتعلّمينه ستّ مرّات.
 * وهذا هو الفرق بين نسقٍ وبين مجموعة بطاقات.
 *
 * ## قواعد صارمة
 *
 * **العلامة تظهر دائماً** — حتى عند صفر بالمئة. مؤشّرٌ يختفي عند الصفر يجعل
 * الشاشة تبدو معطوبة وهي سليمة، وهذه أكثر الحالات ظهوراً في الأسابيع الأولى.
 *
 * **الجمري على العلامة وحدها.** فهي «ما هو حيّ» — موضعك الآن. والمدى
 * والعتبات حبرٌ باهت. ولا يُلوَّن الرقم المرافق أبداً.
 *
 * **`value` و`max` بلا وحدة.** المكوّن يقيس نسبة، ولا يعرف دولاراً من نقطة.
 * النصّ المعروض يأتي جاهزاً في `readout` — فلا يُعيد المكوّن تنسيق الأرقام
 * ولا يخترع تقريباً لا تعرفينه.
 */
export interface HaddThreshold {
  /** موضع العتبة على المدى نفسه (بوحدة `value`). */
  at: number;
  /** لهجة العتبة: حدٌّ محمود أخضر، أو خطرٌ أحمر، أو محايد. */
  tone?: 'neutral' | 'positive' | 'negative';
}

export interface HaddProps {
  /** القيمة الحالية. تُقصّ إلى [`min`, `max`] عند العرض فقط. */
  value: number;
  /** نهاية المدى. */
  max: number;
  /** بداية المدى. الافتراضي صفر. */
  min?: number;
  /** التسمية فوق الخطّ يميناً. */
  label?: string;
  /** النصّ فوق الخطّ يساراً — **جاهزاً منسَّقاً**، لا يُنسَّق هنا. */
  readout?: string;
  /** العتبات المرسومة على المدى. */
  thresholds?: readonly HaddThreshold[];
  /** يملأ ما قبل العلامة. أطفئيه حين تكون القيمة موضعاً لا مقداراً. */
  showFill?: boolean;
  style?: ViewStyle;
  testID?: string;
  /**
   * وصفٌ منطوق كامل. حين يُترك، يُركَّب من `label` و`readout` — وهما نصّان
   * عربيّان أصلاً، فلا يُقرأ للمستخدمة رقمٌ بلا معناه.
   */
  accessibilityLabel?: string;
}

// **المدى كان لا يُرى.** `border` على السطح يبلغ 1.37:1 في الفاتح
// و1.51:1 في الداكن، وعتبة WCAG لعناصر الواجهة غير النصّية 3:1. فكان
// يُرى الشاهدُ ولا يُرى **ما يُقاس عليه** — أي أنّ العنصر الذي بُني ليقول
// «أين أنتِ من الحدّ» كان يقول «أين أنتِ» وحدها.
const TRACK_HEIGHT = 2;
/** علامتا نهايةٍ تجعلان المدى مقروءاً بلا لون. */
const CAP_WIDTH = 2;
const CAP_HEIGHT = 6;
const TICK_HEIGHT = 13;
const MARK_HEIGHT = 5;
const RAIL_HEIGHT = TICK_HEIGHT;

/** يقصّ نسبةً إلى [0, 1] ويحرس القسمة على صفر ومدىً مقلوباً. */
function ratio(value: number, min: number, max: number): number {
  const span = max - min;
  if (!Number.isFinite(span) || span <= 0) return 0;
  const r = (value - min) / span;
  if (!Number.isFinite(r)) return 0;
  return Math.min(1, Math.max(0, r));
}

export function Hadd({
  value,
  max,
  min = 0,
  label,
  readout,
  thresholds = [],
  showFill = true,
  style,
  testID,
  accessibilityLabel,
}: HaddProps): React.JSX.Element {
  const theme = useTheme();
  const pos = ratio(value, min, max);

  // RTL: البداية يمين. النسبة تُقاس من اليمين، فلا يُعكس المعنى مع الاتجاه.
  const fromStart = (r: number): ViewStyle => ({ right: `${r * 100}%` });

  const toneColor = (tone: HaddThreshold['tone']): string => {
    if (tone === 'positive') return theme.colors.positive;
    if (tone === 'negative') return theme.colors.negative;
    return theme.colors.borderStrong;
  };

  const spoken =
    accessibilityLabel ??
    [label, readout].filter(Boolean).join('، ') ??
    undefined;

  return (
    <View style={style} testID={testID}>
      {(label || readout) && (
        <View
          style={{
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            marginBottom: theme.spacing.xs,
          }}
        >
          {label ? (
            <Text variant="caption" tone="secondary">
              {label}
            </Text>
          ) : (
            <View />
          )}
          {readout ? (
            <Text variant="caption" tabular>
              {readout}
            </Text>
          ) : null}
        </View>
      )}

      <View
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={spoken}
        accessibilityValue={{ min, max, now: value }}
        style={{ height: RAIL_HEIGHT, justifyContent: 'center' }}
      >
        {/* المدى */}
        <View
          style={{
            position: 'absolute',
            right: 0,
            left: 0,
            height: TRACK_HEIGHT,
            backgroundColor: theme.colors.borderStrong,
          }}
        />

          {/* طرفا المدى — يُقرأ المدى بهما حتى بلا لون. */}
          <View
            testID="hadd-cap-start"
            style={{
              position: 'absolute',
              right: 0,
              width: CAP_WIDTH,
              height: CAP_HEIGHT,
              top: -(CAP_HEIGHT - TRACK_HEIGHT) / 2,
              backgroundColor: theme.colors.borderStrong,
            }}
          />
          <View
            testID="hadd-cap-end"
            style={{
              position: 'absolute',
              left: 0,
              width: CAP_WIDTH,
              height: CAP_HEIGHT,
              top: -(CAP_HEIGHT - TRACK_HEIGHT) / 2,
              backgroundColor: theme.colors.borderStrong,
            }}
          />

        {/* المستهلَك */}
        {showFill && pos > 0 ? (
          <View
            style={{
              position: 'absolute',
              right: 0,
              width: `${pos * 100}%`,
              height: TRACK_HEIGHT,
              backgroundColor: theme.colors.textTertiary,
            }}
          />
        ) : null}

        {/* العتبات */}
        {thresholds.map((t, i) => (
          <View
            key={`${t.at}-${i}`}
            style={{
              position: 'absolute',
              width: 1,
              height: MARK_HEIGHT,
              backgroundColor: toneColor(t.tone),
              ...fromStart(ratio(t.at, min, max)),
            }}
          />
        ))}

        {/* الموضع الآن — الجمري، وهو ظاهرٌ دائماً ولو كانت النسبة صفراً */}
        <View
          testID={testID ? `${testID}-tick` : undefined}
          style={{
            position: 'absolute',
            width: 2,
            height: TICK_HEIGHT,
            backgroundColor: theme.colors.accent,
            ...fromStart(pos),
          }}
        />
      </View>
    </View>
  );
}
