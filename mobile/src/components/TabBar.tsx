import React from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { usePathname, useRouter } from 'expo-router';

import { useTheme } from '@/theme';
import { MIN_TOUCH_TARGET } from '@/theme/tokens';
import { Text } from './Text';

interface Tab {
  path: string;
  label: string;
  /** الشاشات التي تُعتبر «داخل» هذا التبويب، فيبقى نشطاً وأنتِ فيها. */
  owns: string[];
}

/**
 * التبويبات الأربعة.
 *
 * مبنيّة على **الأسئلة التي يطرحها المنتج**، لا على أقسام البيانات:
 *   الرئيسية → ماذا يحدث الآن؟
 *   القرار   → لماذا قرّر ما قرّر؟
 *   المحفظة  → أين مالي؟
 *   النظام   → هل هو بخير؟
 */
export const TABS: Tab[] = [
  { path: '/home', label: 'الرئيسية', owns: ['/home'] },
  { path: '/decision', label: 'القرار', owns: ['/decision', '/scan', '/intelligence', '/profiles'] },
  { path: '/position', label: 'المحفظة', owns: ['/position', '/history', '/performance'] },
  { path: '/system', label: 'النظام', owns: ['/system', '/providers', '/audit', '/settings', '/notifications', '/emergency'] },
];

/**
 * شريط التبويبات.
 *
 * **الجمري هنا وحده** — على التبويب النشط. وهذا كل ما يلوّنه في الشاشة:
 * ما هو *حيّ*، لا ما يحمل قيمة. والأرقام تبقى حبراً.
 *
 * ولا يُستعمل أيقونات: أربع كلمات عربية تُقرأ فوراً، وأيقونةٌ مجرّدة لـ«القرار»
 * تحتاج تعلّماً. الوضوح قبل الأناقة حين يكون المستخدم واحداً.
 */
export function TabBar(): React.JSX.Element {
  const theme = useTheme();
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();

  return (
    <View
      accessibilityRole="tablist"
      style={{
        flexDirection: 'row',
        borderTopWidth: 1,
        borderTopColor: theme.colors.border,
        backgroundColor: theme.colors.background,
        paddingBottom: Math.max(insets.bottom, theme.spacing.sm),
        paddingTop: theme.spacing.sm,
        paddingHorizontal: theme.spacing.sm,
        gap: theme.spacing.xs,
      }}
    >
      {TABS.map((tab) => {
        const active = tab.owns.some((p) => pathname === p || pathname.startsWith(`${p}/`));
        return (
          <Pressable
            key={tab.path}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={tab.label}
            testID={`tab-${tab.path.slice(1)}`}
            onPress={() => {
              if (!active) {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace(tab.path as any);
              }
            }}
            style={{
              flex: 1,
              minHeight: MIN_TOUCH_TARGET,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: theme.radii.pill,
              paddingVertical: theme.spacing.xs,
              backgroundColor: active ? theme.colors.accent : 'transparent',
            }}
          >
            <Text variant="micro" tone={active ? 'onAccent' : 'secondary'}>
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
