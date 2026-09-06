import React from 'react';
import { View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { TRADING_ENVIRONMENT } from '@/api/config';
import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { fontFamilies } from '@/theme/tokens';
import { Text } from './Text';

/**
 * رأسُ التطبيق — `.chead` في النموذج المعتمد.
 *
 * كان **غيرَ موجودٍ إطلاقاً**: تفتح الشاشة على تاريخٍ وشارةِ بيئة، فلا شيء
 * يقول اسمَ التطبيق ولا يحمل هويّته. والرأسُ في النموذج أربعةُ عناصر:
 *
 *   · مربّعُ الشعار 36×36، استدارة 12، بتدرّج مرجان→جمر.
 *   · «مِثْراة» بخطّ Reem Kufi 18، وتحته سطرٌ 9.
 *   · حبّةُ البيئة — `DEMO` بلون الكثيب على الجمر الخافت.
 *   · صورةٌ دائرية 35 بحدٍّ دافئ.
 *
 * وحبّةُ البيئة هنا لا في بطاقةٍ سادسة: سؤال «تجريبي أم حقيقي؟» هو السؤال
 * الوحيد الذي خطؤه غير قابل للاستدراك.
 */
export function AppHeader(): React.JSX.Element {
  const theme = useTheme();
  const live = TRADING_ENVIRONMENT === 'REAL';

  return (
    <View
      accessible={false}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: theme.spacing.sm,
        paddingBottom: theme.spacing.md,
      }}
    >
      {/* الشعار والاسم */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <LinearGradient
          colors={[theme.colors.accentGlow, theme.colors.accent]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={{
            width: 36,
            height: 36,
            borderRadius: 12,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text
            variant="bodyStrong"
            style={{
              fontFamily: fontFamilies.logo,
              fontSize: 18,
              color: theme.colors.textOnAccent,
            }}
          >
            مـ
          </Text>
        </LinearGradient>
        <View>
          <Text
            variant="bodyStrong"
            accessibilityRole="header"
            style={{ fontFamily: fontFamilies.logo, fontSize: 18 }}
          >
            {t.gate.title}
          </Text>
          <Text variant="micro" tone="tertiary" style={{ fontSize: 9 }}>
            {t.app.tagline}
          </Text>
        </View>
      </View>

      {/* البيئة ثم الحساب */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm }}>
        <View
          accessible
          accessibilityLabel={`بيئة التداول: ${TRADING_ENVIRONMENT}`}
          style={{
            paddingVertical: 6,
            paddingHorizontal: 9,
            borderRadius: 20,
            backgroundColor: live ? theme.colors.negativeSoft : theme.colors.accentSoft,
          }}
        >
          <Text
            variant="micro"
            tabular
            style={{
              fontSize: 9,
              letterSpacing: 0.8,
              color: live ? theme.colors.negative : theme.colors.caution,
            }}
          >
            {TRADING_ENVIRONMENT}
          </Text>
        </View>
        <View
          accessible={false}
          style={{
            width: 35,
            height: 35,
            borderRadius: 999,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: theme.colors.surfaceSunken,
            borderWidth: 1,
            borderColor: theme.colors.navBorder,
          }}
        >
          <Text variant="micro" tone="secondary" style={{ fontSize: 11 }}>
            مآ
          </Text>
        </View>
      </View>
    </View>
  );
}
