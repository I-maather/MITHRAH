import React from 'react';
import { View } from 'react-native';

import { TRADING_ENVIRONMENT } from '@/api/config';
import { useServerEnvironment } from '@/api/environment';
import { t } from '@/i18n';
import { useTheme, type ToneName } from '@/theme';
import { StatusPill } from './StatusPill';
import { Text } from './Text';

/**
 * شارةُ البيئة — **ثابتة في رأس كل شاشة، ولا تُمرَّر**.
 *
 * السؤال «تجريبي أم حقيقي؟» هو السؤال الوحيد في هذا التطبيق الذي **خطؤه
 * غير قابل للاستدراك**. وكان جوابه قبل هذه الشارة تلميحاً بحجم 11pt بلونٍ
 * ثالثي داخل البطاقة السادسة في ترتيب التمرير.
 *
 * وتجمع مصدرين لأنّ أحدهما لا يكفي:
 *
 *     TRADING_ENVIRONMENT   ما بُني عليه التطبيق — ثابتٌ منذ لحظة البناء
 *     broker.is_demo        أين يتداول الخادم الآن — يتغيّر أثناء الاستعمال
 *
 * **واختلافهما يُعرَض إنذاراً لا تفصيلاً.** نسخةٌ بُنيت للتجريب موصولةٌ
 * بحسابٍ حقيقي أخطرُ من الاثنين معاً.
 */
export function EnvironmentBadge({ testID = 'environment-badge' }: { testID?: string }): React.JSX.Element {
  const theme = useTheme();
  const server = useServerEnvironment();
  const build = TRADING_ENVIRONMENT.toUpperCase();

  const buildIsDemo = build === 'DEMO';
  const buildIsReal = build === 'REAL' || build === 'LIVE';
  const buildKnown = buildIsDemo || buildIsReal;

  let tone: ToneName = 'caution';
  let label: string;
  let note: string | null = null;

  if (!buildKnown) {
    tone = 'negative';
    label = t.environment.unset;
    note = t.environment.unsetNote;
  } else if (server === 'UNKNOWN') {
    tone = buildIsReal ? 'negative' : 'caution';
    label = buildIsDemo ? t.environment.demo : t.environment.real;
    note = t.environment.serverUnknown;
  } else if ((server === 'DEMO') === buildIsDemo) {
    tone = buildIsDemo ? 'caution' : 'negative';
    label = buildIsDemo ? t.environment.demo : t.environment.real;
  } else {
    // **التعارض بذاته إنذار.**
    tone = 'negative';
    label = t.environment.conflict;
    note = buildIsDemo ? t.environment.conflictBuildDemo : t.environment.conflictBuildReal;
  }

  return (
    <View testID={testID} style={{ gap: theme.spacing.xxs }}>
      <StatusPill
        testID={`${testID}-pill`}
        label={label}
        tone={tone}
        accessibilityLabel={note === null ? label : `${label} — ${note}`}
      />
      {note === null ? null : (
        <Text variant="caption" tone="secondary" testID={`${testID}-note`}>
          {note}
        </Text>
      )}
    </View>
  );
}
