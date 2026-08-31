import React from 'react';
import { Text as RNText, type StyleProp, type TextStyle } from 'react-native';

import { useTheme } from '@/theme';
import { fontFamilies } from '@/theme/tokens';
import type { TypographyKey } from '@/theme/tokens';
import { textStart } from '@/i18n/rtl';

export type TextTone =
  | 'primary'
  | 'secondary'
  | 'tertiary'
  | 'accent'
  | 'positive'
  | 'negative'
  | 'caution'
  | 'info'
  | 'onAccent';

interface TextProps {
  children: React.ReactNode;
  variant?: TypographyKey;
  tone?: TextTone;
  align?: 'start' | 'center' | 'end';
  style?: StyleProp<TextStyle>;
  numberOfLines?: number;
  /** يُمرَّر إلى VoiceOver حين يختلف المنطوق عن المكتوب (أرقام، رموز). */
  accessibilityLabel?: string;
  accessibilityRole?: 'header' | 'text' | 'summary';
  testID?: string;
  /** الأرقام تُعرض بأرقام لاتينية ثابتة العرض كي لا ترقص عند التحديث. */
  tabular?: boolean;
}

/**
 * نصّ التطبيق.
 *
 * DYNAMIC TYPE
 * `allowFontScaling` يبقى مفعّلاً دائماً (لا يُطفأ في أي موضع)، فيتبع النص
 * إعداد حجم الخط في iOS. `maxFontSizeMultiplier` مأخوذ من رمز الطباعة نفسه:
 * العناوين الكبيرة تُحدّ أكثر من نصّ المتن، كي لا يدفع عنوانٌ ضخم الرقمَ الذي
 * يصفه خارج الشاشة، مع بقاء المتن قابلاً للتكبير حتى ٢٤٠٪.
 */
export function Text({
  children,
  variant = 'body',
  tone = 'primary',
  align = 'start',
  style,
  numberOfLines,
  accessibilityLabel,
  accessibilityRole,
  testID,
  tabular = false,
}: TextProps): React.JSX.Element {
  const theme = useTheme();
  const scale = theme.typography[variant];
  //: الأرقام تأخذ الوجه السيريفي: كل ما هو `tabular` أو من مقاسات `numeric`.
  const numbersFace = tabular || variant === 'numeric' || variant === 'numericLarge';

  const colorFor = (): string => {
    switch (tone) {
      case 'secondary':
        return theme.colors.textSecondary;
      case 'tertiary':
        return theme.colors.textTertiary;
      case 'accent':
        return theme.colors.accent;
      case 'positive':
        return theme.colors.positive;
      case 'negative':
        return theme.colors.negative;
      case 'caution':
        return theme.colors.caution;
      case 'info':
        return theme.colors.info;
      case 'onAccent':
        return theme.colors.textOnAccent;
      case 'primary':
      default:
        return theme.colors.textPrimary;
    }
  };

  const textAlign: TextStyle['textAlign'] =
    align === 'center' ? 'center' : align === 'end' ? 'auto' : textStart();

  return (
    <RNText
      allowFontScaling
      maxFontSizeMultiplier={scale.maxScale}
      numberOfLines={numberOfLines}
      accessibilityLabel={accessibilityLabel}
      accessibilityRole={accessibilityRole}
      testID={testID}
      style={[
        {
          fontSize: scale.size,
          lineHeight: scale.lineHeight,
          fontWeight: scale.weight,
          color: colorFor(),
          textAlign,
          writingDirection: 'rtl',
        },
        tabular ? { fontVariant: ['tabular-nums'] } : null,
        // العائلة تحمل الوزن، فيُسقَط `fontWeight` — وإلا اصطنع iOS وزناً مشوّهاً.
        { fontFamily: numbersFace ? fontFamilies.numeric : fontFamilies.arabic[scale.weight],
          fontWeight: undefined },
        style,
      ]}
    >
      {children}
    </RNText>
  );
}
