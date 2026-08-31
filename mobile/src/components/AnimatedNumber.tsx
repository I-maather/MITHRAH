import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, View } from 'react-native';

import { useTheme } from '@/theme';
import { motion } from '@/theme/tokens';
import type { TypographyKey } from '@/theme/tokens';
import { Text } from './Text';

interface AnimatedNumberProps {
  /** القيمة الحالية. `null` تعني **لم تصل** — ولا تُعرض صفراً. */
  value: number | null | undefined;
  /** خانات عشرية ثابتة كي لا يتغيّر عرض الرقم أثناء العدّ. */
  decimals?: number;
  /** لاحقة نصّية (دولار، نقطة…). تبقى ثابتة ولا تُلوَّن. */
  unit?: string;
  variant?: TypographyKey;
  /**
   * `true` ⇒ الإشارة والّلون يتبعان علامة القيمة (ربح/خسارة).
   * `false` ⇒ رقم محايد بلون الحبر — وهو الافتراضي.
   */
  signed?: boolean;
  /** نطق بديل لـVoiceOver. */
  accessibilityLabel?: string;
  testID?: string;
}

const fmt = (n: number, decimals: number): string =>
  Math.abs(n).toFixed(decimals);

/**
 * رقمٌ حيّ.
 *
 * ثلاث قواعد تحكم هذا المكوّن، وكلها مقصودة:
 *
 * 1. **الإشارة تُعرض دائماً مع اللون** (`+` أو `−`). اللون يعطي السرعة،
 *    والإشارة تضمن أن المعنى لا يضيع في التدرّج الرمادي ولا عند عمى الألوان.
 *    هذا هو تحديداً العيب الذي وُجد في `RiskMeter` — ولا يُعاد هنا.
 *
 * 2. **«لم تصل» ليست صفراً.** `null` تُعرض «غير متاح» بلا حركة ولا لون.
 *
 * 3. **الحركة زينة قابلة للإطفاء.** مع «تقليل الحركة» تقفز القيمة فوراً،
 *    ولا يعتمد أي معنى على الانتقال نفسه.
 */
export function AnimatedNumber({
  value,
  decimals = 2,
  unit,
  variant = 'numericLarge',
  signed = false,
  accessibilityLabel,
  testID,
}: AnimatedNumberProps): React.JSX.Element {
  const theme = useTheme();
  const missing = value === null || value === undefined || Number.isNaN(value);

  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    // `AccessibilityInfo` قد لا يكون كاملاً في كل بيئة (اختبارات، نسخ قديمة).
    // فحصُ وجود الدالة قبل استدعائها ليس دفاعاً زائداً: استدعاء `.then` على
    // `undefined` يُسقط الشجرة كلها — وهذا بالضبط سبب الشاشة السوداء سابقاً.
    let alive = true;
    try {
      const probe = AccessibilityInfo?.isReduceMotionEnabled?.();
      if (probe && typeof probe.then === 'function') {
        probe.then((on: boolean) => alive && setReduceMotion(on)).catch(() => undefined);
      }
    } catch {
      // تعذّر القياس ⇒ نُبقي الحركة. الحركة زينة، وغيابُ القياس لا يبرّر تعطيلها.
    }
    const sub = AccessibilityInfo?.addEventListener?.('reduceMotionChanged', setReduceMotion);
    return () => {
      alive = false;
      sub?.remove?.();
    };
  }, []);

  const target = missing ? 0 : (value as number);
  const anim = useRef(new Animated.Value(target)).current;
  const flash = useRef(new Animated.Value(0)).current;
  const [shown, setShown] = useState(target);
  const previous = useRef(target);

  useEffect(() => {
    const id = anim.addListener(({ value: v }) => setShown(v));
    return () => anim.removeListener(id);
  }, [anim]);

  useEffect(() => {
    if (missing) return;
    const changed = previous.current !== target;
    previous.current = target;

    if (reduceMotion) {
      anim.setValue(target);
      setShown(target);
      return;
    }

    Animated.timing(anim, {
      toValue: target,
      duration: motion.base,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false, // القيمة تُقرأ في JS لتُصاغ نصّاً
    }).start();

    // ومضة خفيفة عند التغيّر — إشارة أن الرقم حيّ، لا معلومة بذاتها.
    if (changed) {
      flash.setValue(1);
      Animated.timing(flash, {
        toValue: 0,
        duration: motion.slow,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }).start();
    }
  }, [target, missing, reduceMotion, anim, flash, motion.base, motion.slow]);

  if (missing) {
    return (
      <Text variant={variant} tone="tertiary" tabular testID={testID}>
        غير متاح
      </Text>
    );
  }

  const positive = shown > 0;
  const negative = shown < 0;
  const tone = signed ? (positive ? 'positive' : negative ? 'negative' : 'primary') : 'primary';
  const sign = signed ? (positive ? '+' : negative ? '−' : '') : '';
  const body = `${sign}${fmt(shown, decimals)}`;

  return (
    <Animated.View
      style={{ opacity: flash.interpolate({ inputRange: [0, 1], outputRange: [1, 0.55] }) }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: theme.spacing.xs }}>
        <Text
          variant={variant}
          tone={tone}
          tabular
          accessibilityLabel={accessibilityLabel ?? `${body}${unit ? ` ${unit}` : ''}`}
          testID={testID}
        >
          {body}
        </Text>
        {unit ? (
          <Text variant="caption" tone="secondary">
            {unit}
          </Text>
        ) : null}
      </View>
    </Animated.View>
  );
}
