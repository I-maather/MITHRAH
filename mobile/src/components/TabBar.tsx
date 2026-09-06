import React from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { usePathname, useRouter } from 'expo-router';

import { useTheme } from '@/theme';
import { MIN_TOUCH_TARGET } from '@/theme/tokens';
import { Text } from './Text';

interface Tab {
  /** رمزُ التبويب كما في `.nav` بالنموذج المعتمد. */
  icon: string;
  path: string;
  label: string;
  /** الشاشات التي تُعتبر «داخل» هذا التبويب، فيبقى نشطاً وأنتِ فيها. */
  owns: string[];
}

/**
 * التبويبات الأربعة — **بأسماء النموذج المعتمد**.
 *
 *   اليوم    → ما الذي يحدث الآن، ولماذا قرّر ما قرّر؟
 *   المحفظة  → أين مالي؟
 *   السجل    → ماذا وقع، ومن اتّخذ قراره؟
 *   النظام   → هل هو بخير؟
 *
 * ## ما تغيّر عن الترتيب السابق، ولماذا
 *
 * كان «القرار» تبويباً مستقلاً و«السجل» مدفوناً داخل «المحفظة». والنموذج
 * المعتمد يعكس ذلك: القرارُ **جزءٌ من يومك** لا وجهةٌ تُقصَد — فبطاقةُ الوكيل
 * ومسارُ اليوم يعيشان في «اليوم» نفسه، وشاشاتُ التفصيل (المسح، الشموع،
 * الذكاء) تبقى تحته. أمّا السجل فسؤالٌ قائمٌ بذاته: «ماذا وقع؟» لا «أين
 * مالي؟» — وخلطُهما هو ما جعل النتائج تُقرأ رصيداً.
 *
 * `owns` ليست زينة: هي التي تُبقي التبويب مضيئاً وأنتِ في شاشةٍ تابعة له،
 * ويحرس اختبارُ التنقّل ألّا تبقى شاشةٌ بلا مالك.
 */
export const TABS: Tab[] = [
  {
    path: '/home',
    label: 'اليوم', icon: '✦',
    owns: ['/home', '/decision', '/scan', '/chart', '/intelligence'],
  },
  { path: '/position', label: 'المحفظة', icon: '◫', owns: ['/position', '/management', '/profiles'] },
  { path: '/history', label: 'السجل', icon: '⌁', owns: ['/history', '/performance'] },
  {
    path: '/system',
    label: 'النظام', icon: '◎',
    owns: ['/system', '/providers', '/audit', '/settings', '/notifications', '/emergency'],
  },
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
      /*
        **شريطٌ عائم، لا شريطٌ ممتدّ بحدٍّ علويّ.**

        `.nav` في النموذج المعتمد: هامشٌ من الجانبين ومن الأسفل، سطحٌ شبه
        شفّاف `rgba(26,21,18,.9)`، حدٌّ `#4A3B2E`، استدارة 20، حشو 7. وكان
        هنا شريطٌ يمتدّ من حافةٍ إلى حافة بخلفيةٍ صلبة — وهو أوّلُ ما يفرّق
        الشكلين عند أسفل الشاشة.
      */
      style={{
        flexDirection: 'row',
        borderWidth: 1,
        borderColor: theme.colors.navBorder,
        backgroundColor: theme.colors.navSurface,
        borderRadius: theme.radii.nav,
        marginHorizontal: 14,
        marginBottom: Math.max(insets.bottom, 12),
        padding: 7,
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
              // أزرارُ `.nav` استدارتها 12 لا حبّة كاملة.
              borderRadius: 12,
              paddingVertical: theme.spacing.xs,
              gap: 2,
              /*
                **النشطُ لونُ نصٍّ لا كتلةٌ ممتلئة.**

                كان مستطيلاً برتقالياً مصمتاً خلف التبويب، فيثقل الشريط
                ويجعله يبدو رخيصاً. وفي النموذج: الرمزُ والاسمُ بلون الجمر،
                وما عداهما رماديّ — بلا خلفيةٍ إطلاقاً.
              */
              backgroundColor: 'transparent',
            }}
          >
            <Text
              variant="micro"
              style={{
                fontSize: 13,
                color: active ? theme.colors.accent : theme.colors.textTertiary,
              }}
            >
              {tab.icon}
            </Text>
            <Text
              variant="micro"
              style={{
                fontSize: 10,
                color: active ? theme.colors.accent : theme.colors.textSecondary,
              }}
            >
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
