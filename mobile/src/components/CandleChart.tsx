import React from 'react';
import { PanResponder, View } from 'react-native';

import type { Candle } from '@/api/types';
import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * رسم الشموع — **بمكوّنات React Native وحدها**.
 *
 * ## لماذا بلا مكتبة
 *
 * لا `react-native-svg` ولا `webview` في هذا التطبيق، وإضافةُ أيّهما تبعيةٌ
 * أصليةٌ جديدة داخل حزمةٍ صُمّمت ألّا تحمل ما لا يلزم: كل تبعية أصلية سطحُ
 * هجومٍ إضافي، وبناءٌ أطول، وشيءٌ يُكسر عند ترقية Expo. والشمعة **مستطيلان**
 * وخيط — وهذا `View` وحده.
 *
 * ## القياس بلا قياس
 *
 * العرض لا يُقاس إطلاقاً: كل شمعة `flex: 1` فتتقاسم العرض المتاح مهما كان.
 * والارتفاع نسبٌ مئوية من ارتفاعٍ ثابت. فلا `onLayout`، ولا إطارٌ أول فارغ،
 * ولا فرقٌ بين ما يُرى على الجهاز وما يُختبر في jest.
 *
 * ## الاتجاه
 *
 * الزمن يجري **يساراً إلى يمين** حتى في واجهةٍ عربية: هذا عرفُ كل رسمٍ مالي،
 * وقلبُه يجعل القراءة المكتسبة تكذب. و`left` في React Native خاصيةٌ فيزيائية
 * لا تنقلب مع RTL (بخلاف `start`/`end`) — فالترتيب هنا مضمونٌ لا مصادفة.
 *
 * ## اللون
 *
 * **الاتجاه يُرمَز بالشكل لا باللون**: الشمعة الصاعدة مجوّفة والهابطة مصمتة —
 * وهو العرف الياباني الأصلي. وذلك لسببين: أن قاعدة النسق تحجز الأخضر للربح
 * المحقّق والأحمر للخسارة، وشمعةٌ صاعدة ليست ربحاً؛ وأن معنى يُحمَل باللون
 * وحده يسقط عند عمى الألوان. فيبقى اللون للمستويات — وهي وحدها التي تحمل
 * مخاطرة.
 */

/** ارتفاع منطقة الرسم. ثابتٌ كي لا يعتمد شيء على قياسٍ لم يقع بعد. */
export const CHART_HEIGHT = 220;

/**
 * أقصى ما يتوسّع به المقياس لاستيعاب مستوى — نصف مدى السعر لكل جهة.
 *
 * ووقفٌ بعيدٌ جداً لا يُمدّ له المقياس: مدّه يضغط الشموع كلّها في خيط،
 * فتضيع الصورة كلها لأجل خطّ واحد. ويُقال حينها إنه خارج المدى.
 */
const MAX_EXPANSION = 0.5;

export interface ChartLevel {
  key: 'entry' | 'stop' | 'target';
  label: string;
  value: number;
  color: string;
}

export interface Parsed {
  o: number;
  h: number;
  l: number;
  c: number;
}

/**
 * يقرأ الشموع أرقاماً. **وما لا يُقرأ يُهمَل ولا يُرسَم على تخمين.**
 *
 * الخادم يرسل نصّاً بدقّة `Decimal`؛ والتحويل يقع هنا عند الرسم وحده، لأن
 * البكسل لا يعرف إلا `number`. وأي حقل غير رقمي يُسقط الشمعة كاملة: شمعةٌ
 * بقاعٍ مخمَّن تكذب أكثر مما تفيد.
 */
export function parseCandles(rows: readonly Candle[]): { bars: Parsed[]; dropped: number } {
  const bars: Parsed[] = [];
  let dropped = 0;
  for (const row of rows) {
    const o = Number(row.o);
    const h = Number(row.h);
    const l = Number(row.l);
    const c = Number(row.c);
    if (![o, h, l, c].every((n) => Number.isFinite(n)) || h < l) {
      dropped += 1;
      continue;
    }
    bars.push({ o, h, l, c });
  }
  return { bars, dropped };
}

export interface ChartScale {
  lo: number;
  hi: number;
  /** المستويات التي وسعها المقياس. */
  drawn: ChartLevel[];
  /** المستويات التي بَعُدت أكثر مما يحتمل المقياس — تُذكَر ولا تُرسَم. */
  offChart: ChartLevel[];
}

/** يبني المقياس من الأسعار، ثم يوسّعه للمستويات القريبة وحدها. */
export function buildScale(bars: readonly Parsed[], levels: readonly ChartLevel[]): ChartScale {
  let lo = Math.min(...bars.map((b) => b.l));
  let hi = Math.max(...bars.map((b) => b.h));
  const span = hi - lo || Math.abs(hi) * 0.001 || 1;
  const floor = lo - span * MAX_EXPANSION;
  const ceiling = hi + span * MAX_EXPANSION;

  const drawn: ChartLevel[] = [];
  const offChart: ChartLevel[] = [];
  for (const level of levels) {
    if (level.value >= floor && level.value <= ceiling) {
      drawn.push(level);
      lo = Math.min(lo, level.value);
      hi = Math.max(hi, level.value);
    } else {
      offChart.push(level);
    }
  }

  // هامشٌ علوي وسفلي كي لا تلتصق أعلى شمعة بحافة الإطار.
  const padding = (hi - lo || span) * 0.06;
  return { lo: lo - padding, hi: hi + padding, drawn, offChart };
}

export interface PreparedChart {
  bars: Parsed[];
  /** شموعٌ لم تُقرأ أرقاماً فأُسقطت. */
  dropped: number;
  scale: ChartScale;
}

/**
 * التجهيز — **دالّة خالصة تُستدعى في الشاشة، لا أثرٌ داخل المكوّن**.
 *
 * كان المكوّن يحسب المقياس ثم يعيده إلى الشاشة عبر `onScale` في `useEffect`.
 * وهذا حلقةٌ لا تنتهي: `candles` و`levels` مصفوفتان تُبنيان في كل تصيير،
 * فتختلف هويّتهما، فيعمل الأثر، فتتغيّر الحالة، فيُعاد التصيير — إلى أن
 * تنفد الذاكرة. وقد نفدت فعلاً في jest قبل أن تصل إلى جهاز.
 *
 * والعلاج ليس ضبط قائمة التبعيات: هو ألّا تُشتَقّ حالةٌ من حالة أصلاً. تُحسَب
 * القيمة حيث تُقرأ، مرّةً في كل تصيير، بلا حالةٍ وبلا أثر.
 */
export function prepareChart(
  candles: readonly Candle[],
  levels: readonly ChartLevel[],
): PreparedChart | null {
  const { bars, dropped } = parseCandles(candles);
  if (bars.length === 0) {
    return null;
  }
  return { bars, dropped, scale: buildScale(bars, levels) };
}

/**
 * أقلّ ما يُعرَض من الشموع. أقلّ من ثمانٍ لا يُقرأ شكلاً.
 * (كان هذا التعليق بأسلوب بايثون `#:` سهواً — وهو حرفٌ غير صالح في TS.)
 */
export const MIN_VISIBLE = 8;

interface CandleChartProps {
  prepared: PreparedChart;
  testID?: string;
  /** يُستدعى بعدد المعروض وموضعه، كي تقول الشاشة «٢٠ من ٦٠». */
  onWindow?: (visible: number, offsetFromEnd: number) => void;
}

/**
 * السحب والتقريب — **بلا مكتبة، وبلا حالةٍ تُعاد بناءً في كل إصبع**.
 *
 * الشاشة رسمٌ ساكن، والمالكة قالت: «ما أقدر أحرّكه». والتحريك هنا ليس
 * زخرفة: ستّون شمعة يومية شهران، وفهمُ ما رآه النظام يحتاج النظر فيما
 * قبلها.
 *
 * والتنفيذ بـ`PanResponder` — وهو في React Native نفسها، فلا تبعية جديدة
 * في تطبيقٍ صُمّم ألّا يحمل ما لا يلزم.
 */
export function CandleChart({ prepared, testID, onWindow }: CandleChartProps): React.JSX.Element {
  const theme = useTheme();
  const all = prepared.bars;

  /**
   * النافذة: كم شمعة تُعرض، وكم شمعة بيننا وبين الأحدث.
   *
   * تُحفظ في `ref` لا في `state` أثناء الإصبع: تحديثُ الحالة عند كل حركة
   * يُعيد بناء الشجرة عشرات المرّات في الثانية فيتقطّع السحب. والحالة
   * تُحدَّث عند نهاية الحركة وحدها.
   */
  const [window, setWindow] = React.useState({ visible: all.length, offset: 0 });
  const start = React.useRef({ visible: all.length, offset: 0 });
  const spanRef = React.useRef(0);

  const clampedVisible = Math.max(MIN_VISIBLE, Math.min(window.visible, all.length));
  const maxOffset = Math.max(0, all.length - clampedVisible);
  const clampedOffset = Math.max(0, Math.min(window.offset, maxOffset));
  const from = all.length - clampedVisible - clampedOffset;
  const bars = all.slice(Math.max(0, from), all.length - clampedOffset);

  React.useEffect(() => {
    // نافذةٌ جديدة عند تبدّل الأداة أو الإطار: تُعاد إلى الكلّ لا إلى
    // موضعٍ من شموعٍ أخرى — وهو ما يجعل الرسم يبدو «عالقاً».
    setWindow({ visible: all.length, offset: 0 });
  }, [all.length]);

  React.useEffect(() => {
    onWindow?.(bars.length, clampedOffset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars.length, clampedOffset]);

  const responder = React.useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: () => {
          start.current = { visible: clampedVisible, offset: clampedOffset };
          spanRef.current = 0;
        },
        onPanResponderMove: (event, gesture) => {
          const touches = event.nativeEvent.touches;
          if (touches.length >= 2) {
            // إصبعان: تقريب. المسافة بينهما تحدّد كم شمعة تُعرض.
            const a = touches[0];
            const b = touches[1];
            if (a === undefined || b === undefined) return;
            const span = Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY);
            if (spanRef.current === 0) {
              spanRef.current = span;
              return;
            }
            const factor = spanRef.current / Math.max(span, 1);
            setWindow((w) => ({
              visible: Math.round(start.current.visible * factor),
              offset: w.offset,
            }));
            return;
          }
          // إصبعٌ واحد: تمرير في الزمن. السحب يميناً يذهب إلى الماضي.
          const perBar = 12;
          setWindow(() => ({
            visible: start.current.visible,
            offset: start.current.offset + Math.round(gesture.dx / perBar),
          }));
        },
      }),
    [clampedVisible, clampedOffset],
  );

  const scale = React.useMemo(
    () => (bars.length > 0 ? buildScale(bars, prepared.scale.drawn) : prepared.scale),
    [bars, prepared.scale],
  );

  const range = scale.hi - scale.lo || 1;
  /** نسبة من الأعلى: السعر الأعلى عند 0٪. */
  const topPct = (price: number): `${number}%` => `${((scale.hi - price) / range) * 100}%`;

  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="image"
      // قارئ الشاشة لا يقرأ مستطيلات. فالوصف رقمٌ لا شكل.
      accessibilityLabel={`رسم شموع: ${bars.length} شمعة، أعلى ${scale.hi.toFixed(5)}، أدنى ${scale.lo.toFixed(5)}.`}
      {...responder.panHandlers}
      style={{
        height: CHART_HEIGHT,
        borderRadius: theme.radii.md,
        borderWidth: 1,
        borderColor: theme.colors.border,
        backgroundColor: theme.colors.surfaceSunken,
        overflow: 'hidden',
      }}
    >
      {/* الشموع أولاً، والمستويات فوقها: خطٌّ يختفي خلف شمعة لا يُقرأ. */}
      <View style={{ flex: 1, flexDirection: 'row', alignItems: 'stretch' }}>
        {bars.map((bar, index) => {
          const rising = bar.c >= bar.o;
          const bodyTop = Math.max(bar.o, bar.c);
          const bodyBottom = Math.min(bar.o, bar.c);
          const bodyHeightPct = Math.max(((bodyTop - bodyBottom) / range) * 100, 0.6);
          return (
            <View key={index} testID={`candle-${index}`} style={{ flex: 1 }}>
              {/* الخيط */}
              <View
                style={{
                  position: 'absolute',
                  left: '50%',
                  width: 1,
                  top: topPct(bar.h),
                  height: `${((bar.h - bar.l) / range) * 100}%`,
                  backgroundColor: theme.colors.textTertiary,
                }}
              />
              {/* الجسم: مجوّف صاعدٌ، مصمتٌ هابط. */}
              <View
                testID={`candle-body-${index}`}
                style={{
                  position: 'absolute',
                  left: 1,
                  right: 1,
                  top: topPct(bodyTop),
                  height: `${bodyHeightPct}%`,
                  borderWidth: 1,
                  borderColor: theme.colors.textSecondary,
                  backgroundColor: rising ? 'transparent' : theme.colors.textSecondary,
                }}
              />
            </View>
          );
        })}
      </View>

      {scale.drawn.map((level) => (
        <View
          key={level.key}
          testID={`chart-level-${level.key}`}
          pointerEvents="none"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: topPct(level.value),
            height: level.key === 'entry' ? 1 : 2,
            backgroundColor: level.color,
            opacity: 0.9,
          }}
        />
      ))}

      {/* حدّا المقياس بالنصّ: خطٌّ بلا رقمٍ يقول «هنا» ولا يقول «كم». */}
      <View style={{ position: 'absolute', top: 4, left: 6 }}>
        <Text variant="micro" tone="tertiary">
          {scale.hi.toFixed(5)}
        </Text>
      </View>
      <View style={{ position: 'absolute', bottom: 4, left: 6 }}>
        <Text variant="micro" tone="tertiary">
          {scale.lo.toFixed(5)}
        </Text>
      </View>
    </View>
  );
}
