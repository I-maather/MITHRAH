import React from 'react';
import { Image, View, useColorScheme, type ViewStyle } from 'react-native';

/**
 * علامة «مثراة».
 *
 * تُعرض صورةً نقطية بثلاث كثافات (‎1x/2x/3x‎) لا SVG — عمداً: العلامة أصلٌ
 * ثابت لا يتغيّر شكله في وقت التشغيل، وتحميلها كصورة يُسقط اعتماداً كاملاً
 * على `react-native-svg` من أجل رسمٍ واحد. والمسارات محفوظة في `brand/*.svg`
 * وهي المصدر الذي تُولَّد منه هذه الصور.
 *
 * **النسخة الداكنة ليست قلباً للألوان**: الحروف تصير ضوءاً، والنقاط تنتقل
 * إلى الجمري الفاتح `#D97B3C` كي تجتاز التباين على الليل — وهي القاعدة
 * نفسها المطبَّقة في نسق الألوان.
 */
export interface WordmarkProps {
  /** الارتفاع بالنقاط. العرض يُحسب من نسبة الأصل. */
  height?: number;
  /** فرض نسخة بعينها. الافتراضي: تتبع نسق الجهاز. */
  scheme?: 'light' | 'dark';
  style?: ViewStyle;
  testID?: string;
  /** الوصف المنطوق. الافتراضي اسم العلامة. */
  accessibilityLabel?: string;
}

//: نسبة العرض إلى الارتفاع، مأخوذة من `viewBox` الأصل — لا تُقدَّر بالعين.
const ASPECT = 1821 / 1191;

const SOURCES = {
  light: require('../../assets/brand/wordmark-light.png'),
  dark: require('../../assets/brand/wordmark-dark.png'),
} as const;

export function Wordmark({
  height = 28,
  scheme,
  style,
  testID,
  accessibilityLabel = 'مثراة',
}: WordmarkProps): React.JSX.Element {
  const system = useColorScheme();
  const mode = scheme ?? (system === 'dark' ? 'dark' : 'light');

  return (
    <View style={style} testID={testID}>
      <Image
        source={SOURCES[mode]}
        accessibilityRole="image"
        accessibilityLabel={accessibilityLabel}
        resizeMode="contain"
        style={{ height, width: height * ASPECT }}
      />
    </View>
  );
}
