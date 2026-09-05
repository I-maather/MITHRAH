import React from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { useSession } from '@/auth/SessionProvider';
import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { PreviewBanner } from './Banner';
import { EnvironmentBadge } from './EnvironmentBadge';
import { Text } from './Text';

interface ScreenProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  /** يعرض شريط «معاينة / Preview» فوق كل شيء. */
  preview?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  testID?: string;
  /**
   * يُخفي زرّ الرجوع في الشاشات الجذرية (الرئيسية) التي يُنتقل إليها
   * بالتبويبات لا بالدفع.
   */
  root?: boolean;
}

/**
 * غلاف الشاشة.
 *
 * يتولّى ثلاثة أشياء لا تُترك للشاشات:
 *   1. المسافات الآمنة والتمرير.
 *   2. تسجيل التفاعل كي يُعاد ضبط مؤقّت القفل التلقائي مع كل لمسة.
 *   3. إظهار وسم المعاينة إن كانت البيانات من `src/fixtures/`.
 */
export function Screen({
  title,
  subtitle,
  children,
  preview = false,
  onRefresh,
  refreshing = false,
  testID,
  root = false,
}: ScreenProps): React.JSX.Element {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const navigation = useRouter();
  const { registerActivity } = useSession();

  return (
    <ScrollView
      testID={testID}
      style={{ flex: 1, backgroundColor: theme.colors.background }}
      contentContainerStyle={{
        padding: theme.spacing.lg,
        paddingBottom: insets.bottom + theme.spacing.huge,
        gap: theme.spacing.lg,
      }}
      onScrollBeginDrag={registerActivity}
      onTouchStart={registerActivity}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh === undefined ? undefined : (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              registerActivity();
              onRefresh();
            }}
            tintColor={theme.colors.textSecondary}
            accessibilityLabel={t.common.refresh}
          />
        )
      }
    >
      {/*
        **البيئة قبل كل شيء.** الشارة في رأس كل شاشة لا تُمرَّر ولا تُطوى:
        سؤال «تجريبي أم حقيقي؟» هو السؤال الوحيد الذي خطؤه غير قابل
        للاستدراك، وكان جوابه تلميحاً بحجم 11pt في البطاقة السادسة.
      */}
      <EnvironmentBadge />

      {/*
        **العنوان مرّةً واحدة.** كان هيدرُ التنقّل يكتبه ثم تكتبه الشاشة،
        فيُهدر أعلى ٩٠ نقطة من أربع عشرة شاشة في تكرارٍ حرفيّ. الهيدر أُطفئ،
        والرجوع صار هنا — حيث العنوان.
      */}
      <View style={{ gap: theme.spacing.xxs }}>
        {root ? null : (
          <Pressable
            testID="screen-back"
            accessibilityRole="button"
            accessibilityLabel={t.common.back}
            onPress={() => {
              registerActivity();
              navigation.back();
            }}
            hitSlop={12}
            style={{
              alignSelf: 'flex-start',
              // **٤٤ نقطة لا تقلّ.** اختبارُ الوصولية أمسك هذا الزرّ ساعةَ
              // وُلد: `paddingVertical` وحده يعطي هدفاً بارتفاع ~٢٦.
              minHeight: 44,
              minWidth: 44,
              justifyContent: 'center',
            }}
          >
            <Text variant="captionStrong" style={{ color: theme.colors.accent }}>
              {`‹ ${t.common.back}`}
            </Text>
          </Pressable>
        )}
        <Text variant="display" accessibilityRole="header">
          {title}
        </Text>
        {subtitle !== undefined ? (
          <Text variant="caption" tone="secondary">
            {subtitle}
          </Text>
        ) : null}
      </View>

      {preview ? <PreviewBanner /> : null}

      {children}
    </ScrollView>
  );
}
