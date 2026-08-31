import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import { BUNDLE_IDENTIFIER } from '@/api/config';
import { useSession } from '@/auth/SessionProvider';
import {
  Banner,
  Card,
  Divider,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  StatusPill,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentConnection } from '@/utils/present';

/**
 * النظام والوسيط.
 *
 * الشاشة تجيب سؤالاً واحداً: **هل أثق بما أراه؟** لذلك تُظهر حالة قناة الاتصال
 * صراحةً (مُعمّاة أم لا، وهل هوية الخادم مؤكدة) قبل أي معلومة عن الوسيط.
 *
 * لا يظهر هنا عنوان وسيط ولا مفتاح ولا رمز جلسة وسيط. التطبيق لا يعرف الوسيط
 * أصلاً؛ ما يعرفه هو ما يقوله خادم مثراة عنه.
 */
export default function SystemScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { client, deviceId } = useSession();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getStatus(), {
    previewData: previewOr(fixtures.status),
  });
  const verdict = client.endpointVerdict();

  if (loading && data === null) {
    return (
      <Screen title={t.system.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  return (
    <Screen
      testID="system-screen"
      title={t.system.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Card testID="transport-card" title={t.system.transport}>
        <StatusPill
          testID="transport-pill"
          label={verdict.ok ? t.system.trusted : t.system.untrusted}
          tone={verdict.ok ? 'positive' : 'negative'}
        />
        <Text variant="caption" tone="secondary" testID="transport-reason">
          {verdict.reasonAr}
        </Text>
        <Divider />
        <Field label={t.system.backend} value={verdict.baseUrl} />
        <Field label={t.system.bundleId} value={BUNDLE_IDENTIFIER} />
        <Field label={t.system.device} value={deviceId} />
      </Card>

      {!verdict.ok ? (
        <Banner
          testID="untrusted-endpoint-banner"
          tone="negative"
          title={t.errors.untrustedTitle}
          body={t.errors.untrustedBody}
        />
      ) : null}

      {data !== null ? (
        <>
          <Card testID="broker-card" title={t.system.broker}>
            <StatusPill
              label={presentConnection(data.broker.connected).labelAr}
              tone={data.broker.connected ? 'positive' : 'negative'}
            />
            <Field label="الاسم" value={data.broker.name} />
            <Field
              label="النوع"
              value={data.broker.is_demo ? t.system.demo : t.system.live}
              tone={data.broker.is_demo ? 'info' : 'caution'}
            />
            <Field label={t.system.accountMasked} value={data.broker.account_masked} />
            <Field
              label={t.system.executionLock}
              value={data.broker.execution_locked ? t.system.locked : t.system.unlocked}
              tone={data.broker.execution_locked ? 'positive' : 'caution'}
              hint="قفل التنفيذ يُدار على الخادم ولا يُفتح من الهاتف."
            />
          </Card>

          <Card testID="killswitch-card" title={t.system.killSwitch}>
            <StatusPill
              testID="killswitch-status-pill"
              label={data.kill_switch.active ? t.system.active : t.system.inactive}
              tone={data.kill_switch.active ? 'negative' : 'positive'}
            />
            <Field label="المُطلِق" value={data.kill_switch.trigger} />
            <Field label="السبب" value={data.kill_switch.reason_ar} />
            <Field label="الوقت" value={formatInstant(data.kill_switch.at_utc)} />
          </Card>
        </>
      ) : (
        <ErrorState error={error} onRetry={refresh} />
      )}

      <Card testID="boundary-card" title={t.system.whatAppCannotDo}>
        {t.boundary.items.map((item) => (
          <View
            key={item}
            accessible
            accessibilityRole="text"
            accessibilityLabel={item}
            style={{ flexDirection: 'row', gap: theme.spacing.sm }}
          >
            <Text variant="caption" tone="negative">
              ×
            </Text>
            <Text variant="caption" tone="secondary" style={{ flex: 1 }}>
              {item}
            </Text>
          </View>
        ))}
      </Card>
    </Screen>
  );
}
