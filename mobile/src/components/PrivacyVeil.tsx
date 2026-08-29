import React from 'react';
import { View } from 'react-native';
import { BlurView } from 'expo-blur';

import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { Text } from './Text';

/**
 * ستر المحتوى في مبدّل التطبيقات.
 *
 * iOS يلتقط لقطة للشاشة عند الانتقال إلى الخلفية، وتلك اللقطة تظهر في مبدّل
 * التطبيقات وقد تُحفظ على القرص. الطبقة هنا تُركَّب عند حالة `inactive` —
 * أي **قبل** اللقطة لا بعدها — فلا يظهر رقم ولا مركز ولا قرار.
 *
 * الطبقة صلبة تحت الضباب لا ضباباً وحده: الضباب وحده قد يترك ملامح أرقام
 * قابلة للتخمين عند تكبير اللقطة.
 */
export function PrivacyVeil(): React.JSX.Element {
  const theme = useTheme();
  return (
    <View
      testID="privacy-veil"
      accessible
      accessibilityLabel={`${t.app.name}. ${t.gate.subtitle}`}
      style={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 1000,
      }}
      pointerEvents="none"
    >
      <BlurView
        intensity={40}
        tint={theme.mode === 'dark' ? 'dark' : 'light'}
        style={{ flex: 1 }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: theme.colors.privacyVeil,
            alignItems: 'center',
            justifyContent: 'center',
            gap: theme.spacing.sm,
          }}
        >
          <Text variant="title" align="center">
            {t.app.name}
          </Text>
          <Text variant="caption" tone="secondary" align="center">
            {t.app.tagline}
          </Text>
        </View>
      </BlurView>
    </View>
  );
}
