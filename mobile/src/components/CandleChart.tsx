import React from 'react';
import { Animated, Dimensions, PanResponder, View, type PanResponderInstance } from 'react-native';

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
 * **الاتجاه يُرمَز بالشكل واللون معاً** — وهذا **قرارٌ نُقض بطلب المالكة**
 * في ٦ سبتمبر ٢٠٢٦، لا بصمت.
 *
 * وكان القرارُ السابق: رماديٌّ كلُّه، صاعدةٌ مجوّفةٌ وهابطةٌ مصمتة، بحجّة أن
 * النسق يحجز الأخضر للربح المحقَّق والأحمر للخسارة، وشمعةٌ صاعدة ليست ربحاً.
 *
 * وحجّةُ النقض — بنصّها: «الشمعة الصاعدة والهابطة معناها مختلفٌ عن النتيجة
 * النهائية حتى لو كانتا أحمر وأخضر». أي أن السياق يفصل: لونٌ داخل رسم سعرٍ
 * يُقرأ اتجاهاً، ولونٌ بجانب رقمِ ربحٍ يُقرأ نتيجة. والعينُ لا تخلط بينهما،
 * بينما تعجز عن قراءة اتجاهِ شمعةٍ رماديّةٍ صغيرةٍ من امتلائها وحده.
 *
 * ويبقى الشكلُ مع اللون — مجوّفةٌ صاعدةٌ ومصمتةٌ هابطة — فمن لا يفرّق بين
 * الأحمر والأخضر يقرأ الاتجاه من الامتلاء. ترميزٌ مزدوجٌ لا بديل.
 *
 * ## المحوران
 *
 * رسمٌ بلا محورين صورةٌ لا قراءة: خطٌّ يقول «هنا» ولا يقول «كم»، وشمعةٌ لا
 * تقول «متى». فعلى اليمين سلّم السعر (وموضعه اليمين عرفُ كل منصّة تداول،
 * لأن آخر شمعةٍ هناك)، وتحت الرسم سلّم الوقت مقروءاً من `t` في كل شمعة —
 * لا من افتراضٍ عن الإطار.
 */

/** ارتفاع منطقة الرسم كاملةً — بالسعر والوقت. */
export const CHART_HEIGHT = 240;

/** ارتفاع شريط الوقت أسفل الرسم. */
const TIME_AXIS_HEIGHT = 18;

/** عرض عمود السعر يميناً. يتّسع لـ«2405.00» ولـ«1.10450». */
const PRICE_GUTTER = 58;

/** عدد خطوط الشبكة الأفقية، الحدّان منها. */
const PRICE_TICKS = 5;

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
  /** بداية الشمعة كما أرسلها الخادم، نصّاً. */
  t: string;
  /** الوقت نفسه بالمللي ثانية، أو `NaN` إن لم يُقرأ — ولا يُخمَّن. */
  ms: number;
}

/**
 * عدد المنازل العشرية **كما كتبها الخادم** — لا كما نظنّ الأداة.
 *
 * `toFixed(5)` كان يكتب الذهب «2405.00000»، وهي دقّةٌ لا يملكها المصدر:
 * ثلاثة أصفارٍ مخترعة في شاشةٍ قاعدتُها ألّا تُعرض قيمة لم تُقرأ. والمنازل
 * تُقرأ من النصّ الوارد، وتُقصَر عند خمسٍ لأن الوسيط لا يزيد عليها.
 */
function decimalsOf(rows: readonly Candle[]): number {
  let seen = 0;
  for (const row of rows) {
    for (const raw of [row.o, row.h, row.l, row.c]) {
      const dot = typeof raw === 'string' ? raw.indexOf('.') : -1;
      if (dot >= 0) {
        seen = Math.max(seen, raw.length - dot - 1);
      }
    }
  }
  return Math.min(seen, 5);
}

/**
 * يقرأ الشموع أرقاماً. **وما لا يُقرأ يُهمَل ولا يُرسَم على تخمين.**
 *
 * الخادم يرسل نصّاً بدقّة `Decimal`؛ والتحويل يقع هنا عند الرسم وحده، لأن
 * البكسل لا يعرف إلا `number`. وأي حقل غير رقمي يُسقط الشمعة كاملة: شمعةٌ
 * بقاعٍ مخمَّن تكذب أكثر مما تفيد.
 *
 * والوقت **لا يُسقط الشمعة**: سعرٌ بلا وقتٍ يبقى سعراً صحيحاً، وغايةُ الوقت
 * وسمُ المحور وحده. فيُقرأ `NaN` ويُترك موضعه في السلّم فارغاً.
 */
export function parseCandles(rows: readonly Candle[]): {
  bars: Parsed[];
  dropped: number;
  decimals: number;
} {
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
    const t = typeof row.t === 'string' ? row.t : '';
    bars.push({
      o,
      h,
      l,
      c,
      t,
      ms: t.length > 0 ? new Date(t).getTime() : Number.NaN,
    });
  }
  return { bars, dropped, decimals: decimalsOf(rows) };
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
  /** المنازل العشرية كما وردت من الخادم. */
  decimals: number;
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
  const { bars, dropped, decimals } = parseCandles(candles);
  if (bars.length === 0) {
    return null;
  }
  return { bars, dropped, decimals, scale: buildScale(bars, levels) };
}

/** أقلّ ما يُعرَض من الشموع. أقلّ من ثمانٍ لا يُقرأ شكلاً. */
export const MIN_VISIBLE = 8;

/** الفارق الزمني بين شمعتين، مقروءاً من الشموع لا مفترضاً من اسم الإطار. */
export function stepOf(bars: readonly Parsed[]): number {
  const gaps: number[] = [];
  for (let i = 1; i < bars.length; i += 1) {
    const a = bars[i - 1];
    const b = bars[i];
    if (a === undefined || b === undefined) continue;
    const gap = b.ms - a.ms;
    if (Number.isFinite(gap) && gap > 0) {
      gaps.push(gap);
    }
  }
  if (gaps.length === 0) {
    return Number.NaN;
  }
  gaps.sort((x, y) => x - y);
  // الوسيط لا المتوسّط: عطلة نهاية الأسبوع فجوةٌ واحدة تفسد المتوسّط.
  return gaps[Math.floor(gaps.length / 2)] ?? Number.NaN;
}

const pad2 = (n: number): string => String(n).padStart(2, '0');

/**
 * وسمُ الشمعة على محور الوقت.
 *
 * الإطار **يُستنتج من الشموع نفسها**: فارقٌ يبلغ يوماً أو يزيد ⇒ التاريخ
 * وحده، وما دونه ⇒ الساعة والدقيقة. ولو لم يُقرأ الوقت لم يُكتب شيء —
 * ووسمٌ مخترع أسوأ من محورٍ ناقص.
 */
export function barLabel(bar: Parsed, stepMs: number): string {
  if (!Number.isFinite(bar.ms)) {
    return '';
  }
  const at = new Date(bar.ms);
  const daily = !Number.isFinite(stepMs) || stepMs >= 20 * 3600 * 1000;
  return daily
    ? `${pad2(at.getDate())}/${pad2(at.getMonth() + 1)}`
    : `${pad2(at.getHours())}:${pad2(at.getMinutes())}`;
}

/** أوّل شمعةٍ وآخرها بالتاريخ الكامل — تحت المحور، لأن «14:30» بلا يوم ناقصة. */
export function spanLabel(bars: readonly Parsed[]): string {
  const first = bars.find((b) => Number.isFinite(b.ms));
  const last = [...bars].reverse().find((b) => Number.isFinite(b.ms));
  if (first === undefined || last === undefined) {
    return '';
  }
  const day = (ms: number): string => {
    const at = new Date(ms);
    return `${pad2(at.getDate())}/${pad2(at.getMonth() + 1)}/${at.getFullYear()}`;
  };
  const a = day(first.ms);
  const b = day(last.ms);
  return a === b ? a : `${a} — ${b}`;
}

interface CandleChartProps {
  /**
   * آخرُ سعرٍ رآه النظام — يُرسَم خطّاً نابضاً فوق الشموع.
   *
   * ولماذا خطٌّ مستقلٌّ لا شمعةٌ تُمدّ: مدُّ آخر شمعةٍ إلى هذا السعر يخترع
   * قمّةً وقاعاً لم يُرسلهما الوسيط. والخطُّ يقول ما يعرفه بالضبط: **هنا
   * السعرُ الآن**، ولا يدّعي شكلَ الشمعة التي لم تُغلق بعد.
   */
  livePrice?: number | null;
  prepared: PreparedChart;
  testID?: string;
  /** يُستدعى بعدد المعروض وموضعه، كي تقول الشاشة «٢٠ من ٦٠». */
  onWindow?: (visible: number, offsetFromEnd: number) => void;
  /** ارتفاعٌ مخالف — الرئيسية تعرض نسخةً أقصر. */
  height?: number;
}

/**
 * السحب والتقريب — **ومَن يمسك اللمسة**.
 *
 * قالت المالكة: «أقدر أكبّر بس ما أحرّك». والعلّة اثنتان، كلتاهما في مَن
 * يملك الإصبع لا في حساب الإزاحة:
 *
 * 1. كان `PanResponder` يُبنى داخل `useMemo` بتبعيّتين تتغيّران عند أول
 *    حركة. و`PanResponder` يحفظ حالة الإيماءة (`dx`) داخل النسخة نفسها؛
 *    فنسخةٌ جديدة في منتصف السحب تبدأ من `dx = 0` أبداً — والإصبع يمضي
 *    والرسم واقف. فيُبنى الآن **مرّةً واحدة**، ويقرأ الحالي من `ref`.
 *
 * 2. `onPanResponderTerminationRequest` يُجيب بنعم افتراضاً. والشاشة
 *    `ScrollView`، فتطلب اللمسة لنفسها فتُعطاها. فيُجاب الآن بلا.
 *
 * والاتجاه يفصل بينهما: سحبٌ أفقيٌّ للرسم، ورأسيٌّ للصفحة. ولو أخذ الرسم
 * كل لمسة لصار جداراً لا يُمرَّر من فوقه.
 */
export function CandleChart({
  prepared,
  testID,
  onWindow,
  livePrice = null,
  height = CHART_HEIGHT,
}: CandleChartProps): React.JSX.Element {
  const theme = useTheme();
  const all = prepared.bars;

  const [window, setWindow] = React.useState({
    visible: all.length,
    offset: 0,
  });
  const start = React.useRef({ visible: all.length, offset: 0 });
  const spanRef = React.useRef(0);

  const clampedVisible = Math.max(MIN_VISIBLE, Math.min(window.visible, all.length));
  const maxOffset = Math.max(0, all.length - clampedVisible);
  const clampedOffset = Math.max(0, Math.min(window.offset, maxOffset));
  const from = all.length - clampedVisible - clampedOffset;
  const bars = all.slice(Math.max(0, from), all.length - clampedOffset);

  /**
   * مرآة النافذة الحالية. تُقرأ داخل مُعالِج لم يُبنَ إلا مرّة، فلا يجوز أن
   * يُغلق على قيمةٍ من تصييرٍ قديم.
   */
  const live = React.useRef({
    visible: clampedVisible,
    offset: clampedOffset,
    total: all.length,
  });
  live.current = {
    visible: clampedVisible,
    offset: clampedOffset,
    total: all.length,
  };

  React.useEffect(() => {
    // نافذةٌ جديدة عند تبدّل الأداة أو الإطار: تُعاد إلى الكلّ لا إلى
    // موضعٍ من شموعٍ أخرى — وهو ما يجعل الرسم يبدو «عالقاً».
    setWindow({ visible: all.length, offset: 0 });
  }, [all.length]);

  React.useEffect(() => {
    onWindow?.(bars.length, clampedOffset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars.length, clampedOffset]);

  /**
   * **طبقةُ اللمس.** معيارُ الرسوم يوجبها بنصّه: «أضِف طبقةَ التحويم —
   * افتراضاً». ورسمٌ يُري الشكلَ ويمنع الرقمَ نصفُ رسم: العينُ ترى أن السعر
   * صعد، ولا تعرف من كم إلى كم.
   *
   * والدخولُ إليها **ضغطةٌ مُمسَكة** لا لمسةٌ عابرة، لسببين: اللمسةُ العابرة
   * تجعل الرسمَ جداراً لا تُمرَّر الصفحةُ من فوقه، والسحبُ الأفقيُّ محجوزٌ
   * للتمرير في الزمن. فإذا استقرّ الإصبعُ ربعَ ثانيةٍ ظهر الخطّان والقراءة،
   * ويتبعان الإصبعَ حتى يُرفَع. وأيُّ حركةٍ قبل ذلك تُلغي الانتظار — فالنيّةُ
   * حينها تمريرٌ لا قراءة.
   */
  const [cursor, setCursor] = React.useState<number | null>(null);
  const cursorRef = React.useRef<number | null>(null);
  const holdRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const plotWidth = React.useRef(0);
  const downRef = React.useRef({ x: 0, y: 0 });
  const barsCountRef = React.useRef(0);
  barsCountRef.current = bars.length;

  const dropCursor = React.useCallback(() => {
    if (holdRef.current !== null) {
      clearTimeout(holdRef.current);
      holdRef.current = null;
    }
    if (cursorRef.current !== null) {
      cursorRef.current = null;
      setCursor(null);
    }
  }, []);

  React.useEffect(() => dropCursor, [dropCursor]);

  /**
   * موضعُ الإصبع → رقمُ الشمعة.
   *
   * والعرضُ **يُقاس** من `onLayout` ولا يُخمَّن من عرض الشاشة ناقصَ ثوابت،
   * لأن ثابتاً واحداً يتغيّر يزيح المؤشّر عن الشمعة التي تحتها الإصبع.
   */
  const indexAt = React.useCallback((x: number): number | null => {
    const width = plotWidth.current;
    const count = barsCountRef.current;
    if (width <= 0 || count <= 0) return null;
    return Math.max(0, Math.min(count - 1, Math.floor((x / width) * count)));
  }, []);

  /**
   * **النبضة.** نقطةٌ عند طرف خطّ السعر الحيّ تخفت وتعود كلَّ تسع أعشار
   * ثانية. وهي الفرقُ بين شاشةٍ تعمل وشاشةٍ متجمّدة: الرقمُ قد لا يتغيّر
   * دقيقةً كاملة، والنبضةُ تقول إن النظام ما زال يقرأ.
   *
   * والبناء كسولٌ لا `useRef(new Animated.Value(1))`: الوسيط يُقيَّم في كل
   * تصييرٍ وإن أُهمل مخرجه.
   */
  const pulseRef = React.useRef<Animated.Value | null>(null);
  if (pulseRef.current === null) {
    pulseRef.current = new Animated.Value(1);
  }
  const pulse = pulseRef.current;

  React.useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 0.2, duration: 900, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 1, duration: 900, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => {
      loop.stop();
    };
  }, [pulse]);

  /**
   * البناء **كسولٌ داخل `ref`**، لا `useRef(PanResponder.create(...))`.
   *
   * الوسيط في `useRef` يُقيَّم في كل تصيير وإن أُهمل مخرجه — فتُبنى نسخةٌ
   * جديدة ثمانَ مرّاتٍ ثم تُرمى. والحارس يعدّ البناء لا الاستعمال، لأن
   * البناء هو ما كان يُفقِد `dx` قيمتَه.
   */
  const responderRef = React.useRef<PanResponderInstance | null>(null);
  if (responderRef.current === null) {
    responderRef.current = PanResponder.create({
      // لا تُؤخذ اللمسة عند النزول: الأخذ عند النزول يجعل الرسم جداراً
      // لا تُمرَّر الصفحة من فوقه.
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (event, gesture) =>
        event.nativeEvent.touches.length >= 2 || Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.4,
      // الصفحة `ScrollView` وتطلب اللمسة. والجواب لا: الإيماءة الأفقية
      // بدأت هنا فتنتهي هنا.
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: () => {
        // التمريرُ يُلغي القراءة: مؤشّرٌ باقٍ على شمعةٍ رحلت يكذب.
        dropCursor();
        start.current = {
          visible: live.current.visible,
          offset: live.current.offset,
        };
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
        /**
         * إصبعٌ واحد: تمرير في الزمن، والسحب يميناً يذهب إلى الماضي.
         *
         * وعرض الشمعة يُشتقّ من عرض الشاشة لا من قياس الرسم: `Dimensions`
         * قراءةٌ متاحة قبل أي تخطيط، بخلاف `onLayout` الذي يترك إطاراً
         * أوّلَ بلا قيمة. والثوابت هي حشوة الشاشة وعمود السعر.
         */
        const plot = Math.max(120, Dimensions.get('window').width - 96 - PRICE_GUTTER);
        const perBar = Math.max(4, plot / Math.max(start.current.visible, 1));
        setWindow(() => ({
          visible: start.current.visible,
          offset: start.current.offset + Math.round(gesture.dx / perBar),
        }));
      },
    });
  }
  const responder = responderRef.current;

  const scale = React.useMemo(
    () => (bars.length > 0 ? buildScale(bars, prepared.scale.drawn) : prepared.scale),
    [bars, prepared.scale],
  );

  const range = scale.hi - scale.lo || 1;
  /** نسبة من الأعلى: السعر الأعلى عند 0٪. */
  const topPct = (price: number): `${number}%` => `${((scale.hi - price) / range) * 100}%`;
  const money = (price: number): string => price.toFixed(prepared.decimals);

  const ticks = Array.from(
    { length: PRICE_TICKS },
    (_, i) => scale.hi - (range * i) / (PRICE_TICKS - 1),
  );

  /**
   * السعرُ الحيّ **إن وقع داخل المقياس**.
   *
   * وخارجَه لا يُرسَم ولا يُمدّ له المقياس: مدُّه يضغط الشموع كلّها في خيط
   * لأجل خطٍّ واحد — وهي القاعدة نفسها المطبَّقة على وقفٍ بعيد.
   */
  const liveInside =
    livePrice !== null && Number.isFinite(livePrice) && livePrice >= scale.lo && livePrice <= scale.hi
      ? livePrice
      : null;

  const cursorIndex = cursor === null ? null : Math.min(cursor, bars.length - 1);
  const cursorBar = cursorIndex === null || cursorIndex < 0 ? undefined : bars[cursorIndex];

  const last = bars.length > 0 ? bars[bars.length - 1] : undefined;
  const step = stepOf(bars);
  /** أربعة أوسمةٍ على محور الوقت — أكثر منها يتراكب على شاشة هاتف. */
  const tickCount = Math.min(4, bars.length);
  const timeTicks: { index: number; label: string }[] = [];
  for (let i = 0; i < tickCount; i += 1) {
    const index = tickCount === 1 ? 0 : Math.round((i * (bars.length - 1)) / (tickCount - 1));
    const bar = bars[index];
    const label = bar === undefined ? '' : barLabel(bar, step);
    if (label !== '' && !timeTicks.some((seen) => seen.index === index)) {
      timeTicks.push({ index, label });
    }
  }

  return (
    <View
      testID={testID}
      style={{
        height,
        /*
          **الإطارُ يزول.** كان صندوقاً محدَّداً داخل بطاقةٍ محدَّدة — علبةٌ
          داخل علبة، وهي أوّلُ ما يُثقل الشاشة. والرسمُ يقف بذاته: الشموعُ
          حدُّه، وسلّمُ السعر إلى جانبه.
        */
        borderRadius: theme.radii.card,
        backgroundColor: 'transparent',
        overflow: 'hidden',
      }}
    >
      <View style={{ flex: 1, flexDirection: 'row' }}>
        {/* ---- منطقة الرسم ---- */}
        <View
          accessible
          accessibilityRole="image"
          // قارئ الشاشة لا يقرأ مستطيلات. فالوصف رقمٌ لا شكل.
          accessibilityLabel={`رسم شموع: ${bars.length} شمعة، أعلى ${money(scale.hi)}، أدنى ${money(scale.lo)}.`}
          {...responder.panHandlers}
          style={{ flex: 1 }}
        >
          {/* خطوط الشبكة أولاً: تحت الشموع لا فوقها. */}
          {ticks.map((tick, index) => (
            <View
              key={`grid-${index}`}
              pointerEvents="none"
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: topPct(tick),
                height: 1,
                backgroundColor: theme.colors.border,
                /*
                  **لا شبكةَ أصلاً.** كانت ثلاثةَ خطوطٍ عند 0.5 داخل رسمٍ
                  ارتفاعُه 188، فوقها ثلاثةُ مستويات وحدُّ إطار — تسعةُ
                  خطوطٍ أفقية على مساحةٍ لا تحتمل ثلاثة.

                  والأرقامُ إلى الجانب تحمل المقياس كاملاً، فالخطُّ تحت كل
                  رقمٍ تكرارٌ بصريٌّ له لا إضافة. ويبقى العنصرُ ليحمل موضعَ
                  الوسم، ولا يُرسَم.
                */
                opacity: 0,
              }}
            />
          ))}

          {/* الشموع، ثم المستويات فوقها: خطٌّ يختفي خلف شمعة لا يُقرأ. */}
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'stretch' }}>
            {bars.map((bar, index) => {
              const rising = bar.c >= bar.o;
              const tone = rising ? theme.colors.positive : theme.colors.negative;
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
                      backgroundColor: tone,
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
                      borderColor: tone,
                      backgroundColor: rising ? 'transparent' : tone,
                    }}
                  />
                </View>
              );
            })}
          </View>

          {/* خطّ آخر سعر — أرفع من المستويات، فهو حقيقةٌ لا نيّة. */}
          {last !== undefined ? (
            <View
              testID="chart-last-line"
              pointerEvents="none"
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: topPct(last.c),
                height: 1,
                backgroundColor: theme.colors.textSecondary,
                opacity: 0.5,
              }}
            />
          ) : null}

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
                /*
                  المستوياتُ تبقى — هي وحدها التي تحمل مخاطرة — لكنها
                  تهمس: 0.45 لا 0.9. الخطُّ الصارخ فوق الشموع يسرق القراءة
                  من السعر نفسه.
                */
                opacity: 0.45,
              }}
            />
          ))}

          {/* وسمُ كل مستوى عند طرفه: ثلاثة خطوطٍ ملوّنة بلا أسماء تُحفَظ
              ولا تُقرأ. والوسم يساراً كي لا يزاحم عمود السعر. */}
          {scale.drawn.map((level) => (
            <View
              key={`tag-${level.key}`}
              testID={`chart-level-tag-${level.key}`}
              pointerEvents="none"
              style={{
                position: 'absolute',
                left: 4,
                top: topPct(level.value),
                transform: [{ translateY: -7 }],
                paddingHorizontal: 4,
                borderRadius: 3,
                backgroundColor: level.color,
              }}
            >
              <Text variant="micro" style={{ color: theme.colors.surface }}>
                {level.label}
              </Text>
            </View>
          ))}

          {/* ---- السعرُ الحيّ ---- */}
          {liveInside !== null ? (
            <View
              testID="chart-live"
              pointerEvents="none"
              style={{ position: 'absolute', left: 0, right: 0, top: topPct(liveInside) }}
            >
              <View
                style={{
                  position: 'absolute',
                  left: 0,
                  right: 0,
                  height: 1,
                  backgroundColor: theme.colors.accent,
                  opacity: 0.7,
                }}
              />
              <Animated.View
                testID="chart-live-pulse"
                style={{
                  position: 'absolute',
                  right: 0,
                  top: -3,
                  width: 7,
                  height: 7,
                  borderRadius: 4,
                  backgroundColor: theme.colors.accent,
                  opacity: pulse,
                }}
              />
            </View>
          ) : null}

          {/* ---- الخطّان والقراءة ---- */}
          {cursorBar !== undefined && cursorIndex !== null ? (
            <View
              testID="chart-crosshair"
              pointerEvents="none"
              style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 }}
            >
              <View
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  left: `${((cursorIndex + 0.5) / Math.max(bars.length, 1)) * 100}%` as `${number}%`,
                  width: 1,
                  backgroundColor: theme.colors.textSecondary,
                  opacity: 0.4,
                }}
              />
              <View
                style={{
                  position: 'absolute',
                  left: 0,
                  right: 0,
                  top: topPct(cursorBar.c),
                  height: 1,
                  backgroundColor: theme.colors.textSecondary,
                  opacity: 0.4,
                }}
              />
              {/*
                القراءةُ تعلو الرسم بأرضيّةٍ صلبة: نصٌّ فوق شموعٍ رماديّة
                يُقرأ نصفَ قراءة. وموضعُها الأعلى ثابتٌ لا يتبع الإصبع، لأن
                لوحةً تقفز تحت اليد أسوأ من لوحةٍ بعيدة.
              */}
              <View
                testID="chart-readout"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  paddingVertical: 4,
                  paddingHorizontal: 7,
                  borderRadius: 10,
                  backgroundColor: theme.colors.background,
                }}
              >
                <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 6 }}>
                  <Text variant="micro" tone="tertiary">
                    {barLabel(cursorBar, step)}
                  </Text>
                  <Text variant="micro">{`إغلاق ${money(cursorBar.c)}`}</Text>
                </View>
                <View style={{ flexDirection: 'row', gap: 8, marginTop: 1 }}>
                  <Text variant="micro" tone="tertiary">{`فتح ${money(cursorBar.o)}`}</Text>
                  <Text variant="micro" tone="tertiary">{`أعلى ${money(cursorBar.h)}`}</Text>
                  <Text variant="micro" tone="tertiary">{`أدنى ${money(cursorBar.l)}`}</Text>
                </View>
              </View>
            </View>
          ) : null}

          {/*
            ---- ملتقِطُ اللمس ----

            طبقةٌ شفّافةٌ فوق الكلّ بـ`box-only`: هي هدفُ اللمسة دائماً، فتأتي
            الإحداثيّاتُ منسوبةً إلى الرسم لا إلى الشمعة التي صادفها الإصبع.
            ولأنها بلا مُعالِجات استجابة، تصعد المفاوضةُ إلى الأب — فيبقى
            التمريرُ والتقريبُ كما كانا.
          */}
          <View
            testID="chart-touch"
            pointerEvents="box-only"
            onLayout={(event) => {
              plotWidth.current = event.nativeEvent.layout.width;
            }}
            onTouchStart={(event) => {
              downRef.current = {
                x: event.nativeEvent.locationX,
                y: event.nativeEvent.locationY,
              };
              if (holdRef.current !== null) clearTimeout(holdRef.current);
              holdRef.current = setTimeout(() => {
                const index = indexAt(downRef.current.x);
                if (index === null) return;
                cursorRef.current = index;
                setCursor(index);
              }, 240);
            }}
            onTouchMove={(event) => {
              const x = event.nativeEvent.locationX;
              if (cursorRef.current !== null) {
                const index = indexAt(x);
                if (index !== null && index !== cursorRef.current) {
                  cursorRef.current = index;
                  setCursor(index);
                }
                return;
              }
              const moved = Math.hypot(
                x - downRef.current.x,
                event.nativeEvent.locationY - downRef.current.y,
              );
              if (moved > 6) dropCursor();
            }}
            onTouchEnd={dropCursor}
            onTouchCancel={dropCursor}
            style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 }}
          />
        </View>

        {/* ---- عمود السعر ---- */}
        <View
          testID="chart-price-axis"
          pointerEvents="none"
          style={{
            width: PRICE_GUTTER,
            borderLeftWidth: 1,
            borderLeftColor: theme.colors.border,
          }}
        >
          {ticks.map((tick, index) => (
            <View
              key={`price-${index}`}
              style={{
                position: 'absolute',
                left: 4,
                right: 2,
                top: topPct(tick),
                transform: [
                  {
                    translateY: index === 0 ? 1 : index === ticks.length - 1 ? -12 : -6,
                  },
                ],
              }}
            >
              <Text variant="micro" tone="tertiary">
                {money(tick)}
              </Text>
            </View>
          ))}
          {last !== undefined ? (
            <View
              testID="chart-last-price"
              style={{
                position: 'absolute',
                left: 2,
                right: 2,
                top: topPct(last.c),
                transform: [{ translateY: -7 }],
                paddingHorizontal: 3,
                borderRadius: 3,
                backgroundColor: theme.colors.textSecondary,
              }}
            >
              <Text variant="micro" style={{ color: theme.colors.surface }}>
                {money(last.c)}
              </Text>
            </View>
          ) : null}
        </View>
      </View>

      {/* ---- محور الوقت ---- */}
      <View
        testID="chart-time-axis"
        pointerEvents="none"
        style={{
          height: TIME_AXIS_HEIGHT,
          borderTopWidth: 1,
          borderTopColor: theme.colors.border,
          marginRight: PRICE_GUTTER,
        }}
      >
        {timeTicks.map((tick) => {
          /**
           * الوسم الأوّل والأخير يُلصقان بالحافّتين لا يُمركَزان: التمركز
           * يدفع نصف النصّ خارج الإطار، و`overflow: hidden` يبتلعه — فيصير
           * «14» بدل «14:30» أو يختفي التاريخ الأوّل كلّه.
           */
          const atStart = tick.index === 0;
          const atEnd = tick.index === bars.length - 1;
          const place = atStart
            ? { left: 2, alignItems: 'flex-start' as const }
            : atEnd
              ? { right: 2, alignItems: 'flex-end' as const }
              : {
                  left: `${(tick.index / Math.max(bars.length - 1, 1)) * 100}%` as `${number}%`,
                  transform: [{ translateX: -28 }],
                  alignItems: 'center' as const,
                };
          return (
            <View
              key={`time-${tick.index}`}
              style={{ position: 'absolute', top: 2, width: 56, ...place }}
            >
              <Text variant="micro" tone="tertiary">
                {tick.label}
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}
