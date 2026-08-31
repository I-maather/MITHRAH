import { View } from 'react-native';
import React, { useEffect } from 'react';
import { Redirect, Stack } from 'expo-router';

import { useSession } from '@/auth/SessionProvider';
import { LoadingState, TabBar } from '@/components';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * الحارس.
 *
 * كل شاشة تحت `(app)` تمرّ من هنا. لا توجد شاشة بيانات واحدة خارج هذا الحارس،
 * ولذلك لا يوجد مسار — لا رابط عميق ولا إشعار ولا استئناف من الخلفية — يعرض
 * رقماً قبل فتح البوابة.
 *
 * حين يسقط القفل (خمول، أو 401، أو إلغاء الجهاز) يعود التوجيه إلى `/` فوراً،
 * ويُفكَّك شجرة الشاشات فلا يبقى محتوى في الذاكرة معروضاً.
 */
export default function AuthenticatedLayout(): React.JSX.Element {
  const theme = useTheme();
  const { status, registerActivity } = useSession();

  useEffect(() => {
    registerActivity();
  }, [registerActivity]);

  if (status === 'BOOTING') {
    return <LoadingState />;
  }

  if (status !== 'UNLOCKED') {
    return <Redirect href="/" />;
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
    <Stack
      screenOptions={{
        headerShown: true,
        headerTitleAlign: 'center',
        headerStyle: { backgroundColor: theme.colors.background },
        headerTintColor: theme.colors.accent,
        headerTitleStyle: { color: theme.colors.textPrimary, fontSize: 17, fontWeight: '600' },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: theme.colors.background },
        headerBackTitle: t.common.back,
        animation: theme.reduceMotion ? 'none' : 'default',
      }}
    >
      <Stack.Screen name="home" options={{ title: t.nav.home, headerShown: false }} />
      <Stack.Screen name="intelligence" options={{ title: t.nav.intelligence }} />
      <Stack.Screen name="decision" options={{ title: t.nav.decision }} />
      <Stack.Screen name="profiles" options={{ title: t.nav.profiles }} />
      <Stack.Screen name="position" options={{ title: t.nav.position }} />
      <Stack.Screen name="history" options={{ title: t.nav.history }} />
      <Stack.Screen name="performance" options={{ title: t.nav.performance }} />
      <Stack.Screen name="providers" options={{ title: t.nav.providers }} />
      <Stack.Screen name="notifications" options={{ title: t.nav.notifications }} />
      <Stack.Screen name="audit" options={{ title: t.nav.audit }} />
      <Stack.Screen name="system" options={{ title: t.nav.system }} />
      <Stack.Screen name="settings" options={{ title: t.nav.settings }} />
      <Stack.Screen name="emergency" options={{ title: t.nav.emergency }} />
    </Stack>
    <TabBar />
    </View>
  );
}
