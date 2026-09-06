import React from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { useTheme } from '@/theme';

/**
 * الزجاج — العنصرُ الحامل في النموذج المعتمد.
 *
 * ## لماذا عنصرٌ قائمٌ بذاته
 *
 * `Card` في هذا التطبيق مكتوبٌ في رأسه: «الفصل بالحدود لا بالظل — أهدأ على
 * العين». وهو حكمٌ معقول في مجرّده، لكنه **نقيضُ النموذج المعتمد نصّاً**:
 * النموذج يبني بطاقاته الرئيسية من أربع طبقاتٍ لا من حدٍّ واحد.
 *
 * فالطبقاتُ الأربع، بقيمها من `qareeb-2026-09-04.html`:
 *
 *   1. طبقةٌ معتمة تحت كل شيء — `rgba(16,15,14,.55)`. وهي التي تُثبّت
 *      التباين مهما كان خلف البطاقة؛ بدونها الزجاجُ يقرأ ما تحته.
 *   2. تدرّجٌ قُطريّ أبيض — من `.10` إلى `.035` بزاوية 135°.
 *   3. حدٌّ `rgba(255,255,255,.15)`.
 *   4. لمعةٌ داخلية بسمك بكسل عند الحافة العليا — `rgba(255,255,255,.09)`.
 *
 * وثلاثتُها الأولى لا تُغني إحداها عن الأخرى: التدرّجُ وحده بلا طبقةٍ
 * سفلى شفافيةٌ لا زجاج، والطبقةُ وحدها بلا تدرّجٍ لونٌ صلبٌ آخر.
 *
 * ## التوهّج
 *
 * `.ai:after` في النموذج دائرةٌ بـ`filter: blur(55px)` وعتامة `.14`.
 * ولا `blur` في React Native إلا `BlurView` — وهي تُموّه ما **خلف** العنصر
 * لا نفسه. فالتوهّجُ هنا حلقاتٌ متراكزة تتناقص عتامتُها، وهي أقربُ ما
 * يُحاكي التدرّجَ الشعاعيّ بلا مكتبةٍ جديدة. والفرقُ يُقال ولا يُخفى.
 */
export interface GlassProps {
  children: React.ReactNode;
  /** لون التوهّج — يُترك فارغاً فلا توهّج. */
  glow?: string;
  /** شريطٌ ملوّن على حافة البداية — `--rail` في النموذج. */
  rail?: string;
  radius?: number;
  padding?: number;
  /*
    **النطق يمرّ.** حين صارت بطاقةُ الوكيل زجاجاً فقدت وصفَها لقارئ الشاشة،
    فأمسكه `qareeb-components`: بطاقةٌ تُقرأ جملةً واحدة صارت شظايا.
  */
  accessible?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

/** حلقاتُ التوهّج: نصفُ القطر يكبر والعتامةُ تصغر. */
const GLOW_RINGS = [
  { size: 120, opacity: 0.055 },
  { size: 156, opacity: 0.04 },
  { size: 196, opacity: 0.028 },
  { size: 240, opacity: 0.018 },
];

export function Glass({
  children,
  glow,
  rail,
  radius,
  padding,
  style,
  testID,
  accessible,
  accessibilityLabel,
}: GlassProps): React.JSX.Element {
  const theme = useTheme();
  const r = radius ?? theme.radii.glass;

  return (
    <View
      testID={testID}
      accessible={accessible ?? false}
      accessibilityLabel={accessibilityLabel}
      style={[
        {
          borderRadius: r,
          borderWidth: 1,
          borderColor: theme.colors.glassBorder,
          padding: padding ?? theme.spacing.lg,
          gap: theme.spacing.md,
          overflow: 'hidden',
          // العزلُ ضروريّ: بدونه يخرج التوهّجُ خارج نصف القطر.
          position: 'relative',
        },
        style,
      ]}
    >
      {/* ١ · الطبقة المعتمة — بها يثبت التباين. */}
      <View
        pointerEvents="none"
        style={[StyleSheet.absoluteFillObject, { backgroundColor: theme.colors.glassBacking }]}
      />

      {/* التوهّج تحت التدرّج كي لا يبتلع لونَه. */}
      {glow !== undefined
        ? GLOW_RINGS.map((ring) => (
            <View
              key={ring.size}
              pointerEvents="none"
              style={{
                position: 'absolute',
                width: ring.size,
                height: ring.size,
                borderRadius: ring.size / 2,
                backgroundColor: glow,
                opacity: ring.opacity,
                // `left` فيزيائيّ لا منطقيّ — والنموذج يضع التوهّج
                // عند الحافة اليسرى الفيزيائية داخل حاويةٍ RTL.
                left: -ring.size / 4,
                top: -ring.size / 2.6,
              }}
            />
          ))
        : null}

      {/* ٢ · التدرّج القُطري. */}
      <LinearGradient
        pointerEvents="none"
        colors={[theme.colors.glassTop, theme.colors.glassBottom]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={StyleSheet.absoluteFillObject}
      />

      {/* ٤ · اللمعةُ عند الحافة العليا — بكسلٌ واحد. */}
      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 1,
          backgroundColor: theme.colors.glassHighlight,
        }}
      />

      {/* الشريطُ الملوّن — الحدُّ الوحيد الملوّن في الشاشة. */}
      {rail !== undefined ? (
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            /*
              `.ai` في النموذج: `border-inline-end: 3px`. والتطبيق يُقلَب
              RTL على مستوى العملية، فحافّةُ **النهاية** هي اليسار
              الفيزيائيّ — وكان الشريطُ على اليمين، أي على الجانب الخطأ.
            */
            left: 0,
            width: 3,
            backgroundColor: rail,
          }}
        />
      ) : null}

      {children}
    </View>
  );
}
