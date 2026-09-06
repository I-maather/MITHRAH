import React from 'react';
import { View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { TRADING_ENVIRONMENT } from '@/api/config';
import { useEndpoint } from '@/api/useEndpoint';
import { fixtures, previewOr } from '@/fixtures';
import { t } from '@/i18n';
import { useTheme } from '@/theme';
import { fontFamilies } from '@/theme/tokens';
import { Text } from './Text';

/**
 * رأسُ التطبيق — `.chead` في النموذج المعتمد.
 *
 * ## الاسمُ ملاصقٌ للمربّع
 *
 * رأته المالكة متباعداً وقالت: «كلمة مثراة اللي هي اللوجو المفروض تكون جو
 * المربع مو بعيد عنو». والسببُ لم يكن ترتيباً بل **فيضاناً**: السطرُ الصغير
 * تحت الاسم كان شعارَ التطبيق كاملاً، فاتّسع العمودُ ودفع المجموعةَ خارج
 * الشاشة. فصار السطرُ قصيراً، والمجموعةُ لا تفيض (`flexShrink`)، والاسمُ
 * ملاصقٌ للمربّع كما في النموذج.
 *
 * ## البيئةُ تُقرأ من الخادم لا من البناء
 *
 * سألت المالكة: «لو بدّلتُه بعدين لحقيقي حيتغير؟» — وكان الجواب **لا**:
 * الحبّةُ كانت تقرأ `TRADING_ENVIRONMENT` المخبوزةَ وقت البناء. فلو حُوِّل
 * الخادمُ إلى الحساب الحقيقي لبقي الرأس يقول «تجريبي» حتى تُبنى نسخةٌ
 * جديدة — وهو بالضبط السؤالُ الذي خطؤه غير قابل للاستدراك.
 *
 * فصارت تقرأ `broker.is_demo` من الخادم. وإن اختلف ما في البناء عمّا يقوله
 * الخادم، **يُقال الاثنان بلونٍ سالب** ولا يُرجَّح أحدهما صامتاً: اختلافُهما
 * نفسُه هو المعلومة.
 */
export function AppHeader(): React.JSX.Element {
  const theme = useTheme();
  const status = useEndpoint((c) => c.getStatus(), { previewData: previewOr(fixtures.status) });

  const built: 'DEMO' | 'REAL' | 'UNSET' =
    TRADING_ENVIRONMENT === 'REAL' ? 'REAL' : TRADING_ENVIRONMENT === 'DEMO' ? 'DEMO' : 'UNSET';

  /** ما يقوله الخادمُ الآن — و`null` تعني «لم يُقرأ» لا «تجريبي». */
  const served: 'DEMO' | 'REAL' | null =
    status.data === null ? null : status.data.broker.is_demo ? 'DEMO' : 'REAL';

  const disagree = served !== null && served !== built;
  const label = served ?? built;
  const live = label === 'REAL';

  const tone = disagree
    ? { bg: theme.colors.negativeSoft, fg: theme.colors.negative }
    : served === null
      ? { bg: theme.colors.surfaceSunken, fg: theme.colors.textTertiary }
      : live
        ? { bg: theme.colors.negativeSoft, fg: theme.colors.negative }
        : { bg: theme.colors.accentSoft, fg: theme.colors.caution };

  const spoken = disagree
    ? `تعارض: الخادم ${served} والبناء ${built}`
    : served === null
      ? 'البيئة لم تُقرأ من الخادم بعد'
      : `بيئة التداول: ${label}`;

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
      {/* الشعار والاسم — وحدةٌ واحدة لا تتباعد ولا تفيض. */}
      {/*
        **المربّعُ يحمل الاسم.**

        قالت المالكة: «المربّعُ يحمل مِثْراة بدل مـ». وكان المربّعُ حرفاً
        والاسمُ إلى جانبه، فصارا شيئين يتباعدان كلّما ضاق العرض. والاسمُ
        داخل الشكل وحدةٌ واحدة لا تنفصل.
      */}
      <LinearGradient
        colors={[theme.colors.accentGlow, theme.colors.accent]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={{
          height: 38,
          borderRadius: 13,
          paddingHorizontal: 14,
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 1,
        }}
      >
        <Text
          variant="bodyStrong"
          accessibilityRole="header"
          numberOfLines={1}
          style={{
            fontFamily: fontFamilies.logo,
            fontSize: 19,
            color: theme.colors.textOnAccent,
          }}
        >
          {t.gate.title}
        </Text>
      </LinearGradient>

      {/* البيئة ثم الحساب */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: theme.spacing.sm,
          flexShrink: 0,
        }}
      >
        <View
          accessible
          accessibilityLabel={spoken}
          testID="header-environment"
          style={{
            paddingVertical: 6,
            paddingHorizontal: 9,
            borderRadius: 20,
            backgroundColor: tone.bg,
          }}
        >
          <Text variant="micro" tabular style={{ fontSize: 9, letterSpacing: 0.8, color: tone.fg }}>
            {disagree ? `${served} ≠ ${built}` : (served ?? '—')}
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
