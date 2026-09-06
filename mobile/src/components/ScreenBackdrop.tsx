import React from 'react';
import { Image, StyleSheet, View, useWindowDimensions } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { useTheme } from '@/theme';

/**
 * خلفيةُ الشاشة — **ليست سوداءَ مسطّحة.**
 *
 * في النموذج المعتمد:
 *
 *     .screen{ background:
 *       radial-gradient(circle at 88% 10%, #3A2318, transparent 34%),
 *       linear-gradient(160deg, #1A1512, #100F0E 60%) }
 *
 * توهّجٌ عنبريّ في الزاوية العليا فوق تدرّجٍ قُطريّ دافئ. وكان التطبيق يرسم
 * `#100F0E` مصمتاً، فتصير الشاشة قائمةَ صناديقَ على سواد مهما ضُبطت أنصافُ
 * الأقطار. وهذه الطبقةُ هي العمقُ والدفء — أوّلُ ما يُفتقد بالعين وآخرُ ما
 * يُذكر بالوصف.
 *
 * ## لماذا صورةٌ للتوهّج
 *
 * `expo-linear-gradient` خطّيٌّ فقط، ولا تدرّجَ شعاعيّاً في React Native بلا
 * مكتبةِ رسمٍ متجهيّ. فالتوهّجُ صورةٌ مولَّدةٌ بقناة ألفا بالقيم نفسها — تدرّجٌ
 * خطّيّ من `#3A2318` إلى الشفاف التامّ — لا تقريبٌ بحلقات.
 *
 * ونصفُ قطرِه يُحسب كما يحسبه CSS: `34%` من المسافة إلى **أبعد زاوية** عن
 * مركزٍ عند (88%, 10%).
 */
export function ScreenBackdrop(): React.JSX.Element {
  const theme = useTheme();
  const { width, height } = useWindowDimensions();

  // مركزُ التوهّج ثم أبعدُ زاويةٍ عنه — كحساب `farthest-corner` في CSS.
  const cx = width * 0.88;
  const cy = height * 0.1;
  const far = Math.hypot(Math.max(cx, width - cx), Math.max(cy, height - cy));
  const radius = far * 0.34;
  const size = radius * 2;

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFillObject}>
      <LinearGradient
        colors={[theme.colors.backdropWarm, theme.colors.background]}
        locations={[0, 0.6]}
        start={{ x: 0.35, y: 0 }}
        end={{ x: 0.65, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />
      <Image
        source={require('../../assets/images/corner-glow.png')}
        style={{
          position: 'absolute',
          width: size,
          height: size,
          left: cx - radius,
          top: cy - radius,
        }}
        resizeMode="stretch"
        accessible={false}
      />
    </View>
  );
}
