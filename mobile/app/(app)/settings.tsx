import React, { useState } from 'react';
import { Pressable, View } from 'react-native';

import Constants from 'expo-constants';

import { AUTO_LOCK_MINUTES, BUNDLE_IDENTIFIER, PREVIEW_DATA_ENABLED } from '@/api/config';
import { useSession } from '@/auth/SessionProvider';
import { maskToken } from '@/auth/tokenStore';
import { Banner, Button, Card, Divider, Field, Screen, StatusPill, Text } from '@/components';
import { isPreviewMode } from '@/fixtures';
import { t } from '@/i18n';
import { MIN_TOUCH_TARGET, useTheme } from '@/theme';

type AppearanceChoice = 'system' | 'light' | 'dark';

/**
 * الإعدادات.
 *
 * ما ليس هنا مقصود: لا تبديل تحليلات (لا تحليلات أصلاً)، ولا إطفاء لستر مبدّل
 * التطبيقات، ولا تمديد للقفل التلقائي بلا حدّ، ولا حقل لأي مفتاح. الإعداد الذي
 * يُضعف الأمان لا يُعرَض كخيار.
 *
 * اختيار المظهر هنا **تفضيل عرض فقط** ويُطبَّق على مستوى النظام في iOS؛
 * التطبيق يتبع النظام افتراضياً ويعرض الخيار للتوضيح.
 */
export default function SettingsScreen(): React.JSX.Element {
  const theme = useTheme();
  const { deviceId, signOut, client } = useSession();
  const [appearance, setAppearance] = useState<AppearanceChoice>('system');
  const [busy, setBusy] = useState(false);
  const verdict = client.endpointVerdict();

  const choices: Array<{ key: AppearanceChoice; label: string }> = [
    { key: 'system', label: t.settings.appearanceSystem },
    { key: 'light', label: t.settings.appearanceLight },
    { key: 'dark', label: t.settings.appearanceDark },
  ];

  return (
    <Screen testID="settings-screen" title={t.settings.title} preview={isPreviewMode()}>
      <Card testID="appearance-card" title={t.settings.appearance}>
        <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
          {choices.map((choice) => {
            const selected = appearance === choice.key;
            return (
              <Pressable
                key={choice.key}
                testID={`appearance-${choice.key}`}
                accessible
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${t.settings.appearance}: ${choice.label}`}
                onPress={() => {
                  setAppearance(choice.key);
                }}
                style={{
                  flex: 1,
                  minHeight: MIN_TOUCH_TARGET,
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: theme.radii.md,
                  borderWidth: 1,
                  borderColor: selected ? theme.colors.accent : theme.colors.border,
                  backgroundColor: selected ? theme.colors.accentSoft : 'transparent',
                  paddingVertical: theme.spacing.sm,
                }}
              >
                <Text variant="caption" tone={selected ? 'accent' : 'secondary'} align="center">
                  {choice.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text variant="micro" tone="tertiary">
          {`الوضع الحالي: ${theme.mode === 'dark' ? t.settings.appearanceDark : t.settings.appearanceLight}`}
        </Text>
      </Card>

      <Card testID="security-card" title={t.settings.security}>
        <Field
          label={t.settings.autoLock}
          value={`${AUTO_LOCK_MINUTES} ${t.settings.minutes}`}
          hint="يُضبط عند البناء، ولا يُمدَّد من داخل التطبيق."
        />
        <Field
          label={t.settings.hideInSwitcher}
          value={t.settings.alwaysOn}
          tone="positive"
          hint="الستر يُركَّب قبل لقطة النظام لا بعدها."
        />
        <Divider />
        <Field
          label="Face ID"
          value="بوابة وصول محلية"
          hint={t.gate.faceIdNote}
        />
      </Card>

      <Card testID="connection-card" title={t.settings.connection}>
        <StatusPill
          label={verdict.ok ? t.system.trusted : t.system.untrusted}
          tone={verdict.ok ? 'positive' : 'negative'}
        />
        <Field label={t.system.backend} value={verdict.baseUrl} />
        <Text variant="caption" tone="secondary">
          {verdict.reasonAr}
        </Text>
      </Card>

      <Card testID="session-card" title={t.settings.session}>
        <Field label={t.system.device} value={deviceId} />
        <Field label={t.system.sessionToken} value={maskToken(deviceId)} hint="مقنَّع دائماً." />
        <Field
          label={t.settings.dataSource}
          value={PREVIEW_DATA_ENABLED ? t.settings.preview : t.settings.live}
          tone={PREVIEW_DATA_ENABLED ? 'caution' : 'positive'}
        />
        <Button
          label={t.settings.signOut}
          kind="quiet"
          tone="neutral"
          busy={busy}
          accessibilityLabel={t.settings.signOut}
          accessibilityHint={t.settings.signOutNote}
          testID="sign-out-button"
          onPress={() => {
            setBusy(true);
            void signOut().finally(() => {
              setBusy(false);
            });
          }}
        />
        <Text variant="micro" tone="tertiary">
          {t.settings.signOutNote}
        </Text>
      </Card>

      <Card testID="about-card" title={t.settings.about}>
        <Field label="الاسم" value={t.app.fullName} />
        <Field label={t.settings.version} value={Constants.expoConfig?.version ?? '—'} />
        <Field label={t.system.bundleId} value={BUNDLE_IDENTIFIER} />
      </Card>

      <Banner
        testID="no-analytics-banner"
        tone="info"
        title="لا تحليلات"
        body="لا يرسل هذا التطبيق أي قياس ولا تتبّع إلى أي طرف. لا SDK تحليلات فيه أصلاً."
      />
    </Screen>
  );
}
