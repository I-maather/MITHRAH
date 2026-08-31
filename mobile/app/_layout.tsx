import React, { useEffect } from 'react';
import { View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { Slot, useRouter } from 'expo-router';
import * as Linking from 'expo-linking';

import { useFonts } from 'expo-font';

import { SessionProvider, useSession } from '@/auth/SessionProvider';
import { CrashGuard, PrivacyVeil, Text } from '@/components';
import { applyRtl, rtlState } from '@/i18n';
import { ThemeProvider, useTheme } from '@/theme';
import { resolveDeepLink } from '@/utils/deepLinks';

/**
 * الجذر.
 *
 * `applyRtl()` تُستدعى هنا **قبل أي رسم**: الاتجاه قرار على مستوى العملية لا
 * على مستوى المكوّن. انظري `src/i18n/rtl.ts` لتفصيل ما يحدث في أول إقلاع.
 */
applyRtl();

/**
 * القشرة. مُصدَّرة بالاسم كي تُختبَر داخل مزوّدين مُحقَنين، فيمكن اختبار
 * سلوك الرابط العميق في حالة «مقفل» وحالة «مفتوح» على حدة.
 */
export function AppShell(): React.JSX.Element {
  const theme = useTheme();
  const { obscured, status, pendingDeepLink, capturePendingDeepLink, consumePendingDeepLink } =
    useSession();
  const router = useRouter();
  const rtl = rtlState();

  // -- التقاط الروابط العميقة ------------------------------------------------
  // الرابط يُحتجَز فقط. لا يُحلّ إلى شاشة قبل فتح البوابة المحلية.
  useEffect(() => {
    let alive = true;
    void Linking.getInitialURL().then((initial) => {
      if (alive && initial !== null) {
        capturePendingDeepLink(initial);
      }
    });
    const sub = Linking.addEventListener('url', (event) => {
      capturePendingDeepLink(event.url);
    });
    return () => {
      alive = false;
      sub.remove();
    };
  }, [capturePendingDeepLink]);

  // -- حلّ الرابط بعد المصادقة فقط --------------------------------------------
  // `pendingDeepLink` في التبعيات عمداً: الرابط قد يصل **بعد** الفتح، وقد يصل
  // قبله ثم يُفتح التطبيق. الحالتان تمرّان من هنا، ولا تمرّ أيّ منهما قبل الفتح.
  useEffect(() => {
    if (status !== 'UNLOCKED' || pendingDeepLink === null) {
      return;
    }
    const pending = consumePendingDeepLink();
    if (pending === null) {
      return;
    }
    const resolved = resolveDeepLink(pending);
    if (resolved.path !== null) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.push(resolved.path as any);
    }
  }, [status, pendingDeepLink, consumePendingDeepLink, router]);

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <StatusBar style={theme.mode === 'dark' ? 'light' : 'dark'} />
      {rtl.restartRequired && rtl.noticeAr !== null ? (
        <View
          style={{
            backgroundColor: theme.colors.infoSoft,
            paddingHorizontal: theme.spacing.lg,
            paddingVertical: theme.spacing.sm,
          }}
        >
          <Text variant="micro" tone="info" testID="rtl-restart-notice">
            {rtl.noticeAr}
          </Text>
        </View>
      ) : null}
      <Slot />
      {/* الستر يُركَّب فوق كل شيء عند مغادرة الواجهة. */}
      {obscured ? <PrivacyVeil /> : null}
    </View>
  );
}

/**
 * بوابة الخطوط.
 *
 * الخطوط تُحمَّل قبل أول رسم، وإلا ظهر النص بخط النظام ثم قفز — وقفزةُ الخط
 * على شاشة أرقام تبدو عطلاً لا انتقالاً.
 *
 * **والفشل لا يُنتج شاشة سوداء.** `error` تُعامَل كـ`loaded`: يُرسَم التطبيق
 * بخط النظام ويعمل كل شيء. خطٌّ ناقص عيبٌ بصري؛ وشاشةٌ سوداء عطلٌ صامت —
 * وقد حدث في هذا المشروع مرة، ولا يتكرّر من بابٍ فتحتُه أنا.
 */
function FontGate({ children }: { children: React.ReactNode }): React.JSX.Element | null {
  const [loaded, error] = useFonts({
    'IBMPlexSansArabic-Regular': require('../assets/fonts/IBMPlexSansArabic-Regular.ttf'),
    'IBMPlexSansArabic-Medium': require('../assets/fonts/IBMPlexSansArabic-Medium.ttf'),
    'IBMPlexSansArabic-SemiBold': require('../assets/fonts/IBMPlexSansArabic-SemiBold.ttf'),
    'IBMPlexSansArabic-Bold': require('../assets/fonts/IBMPlexSansArabic-Bold.ttf'),
    Newsreader: require('../assets/fonts/Newsreader.ttf'),
    ReemKufi: require('../assets/fonts/ReemKufi.ttf'),
    Amiri: require('../assets/fonts/Amiri-Regular.ttf'),
    'Amiri-Bold': require('../assets/fonts/Amiri-Bold.ttf'),
  });
  if (!loaded && !error) {
    return null;
  }
  return <>{children}</>;
}

export default function RootLayout(): React.JSX.Element {
  return (
    // **الحارس فوق كل شيء** — فوق السمة والجلسة معاً. لو انهار أيٌّ منهما
    // ظهرت رسالة عربية بدل شاشة سوداء صمّاء. وقد ظهرت الشاشة السوداء فعلاً.
    <CrashGuard>
      <FontGate>
        <ThemeProvider>
          <SafeAreaProvider>
            <SessionProvider>
              <AppShell />
            </SessionProvider>
          </SafeAreaProvider>
        </ThemeProvider>
      </FontGate>
    </CrashGuard>
  );
}
