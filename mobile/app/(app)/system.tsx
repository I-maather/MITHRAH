import React, { useState } from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import { BUNDLE_IDENTIFIER } from '@/api/config';
import { useSession } from '@/auth/SessionProvider';
import { ApiError } from '@/api/client';
import {
  Banner,
  Card,
  ConfirmButton,
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

  /**
   * تبديل الحساب المقروء منه.
   *
   * النتيجة تُعرض من **نصّ الخادم** (`note_ar`) لا من جملةٍ تُكتب هنا: الخادم
   * وحده يعرف ماذا وقع، وجملةٌ محلّية تصف نجاحاً قد لا يكون وقع هي بالضبط
   * العطل الذي أصاب زرّي الإيقاف والقاطع من قبل.
   */
  const [switching, setSwitching] = useState(false);
  const [switchNote, setSwitchNote] = useState<string | null>(null);
  const [switchOk, setSwitchOk] = useState(false);

  const switchTo = async (target: 'DEMO' | 'LIVE'): Promise<void> => {
    setSwitching(true);
    setSwitchNote(null);
    try {
      const response = await client.switchEnvironment(target);
      setSwitchOk(response.data.accepted);
      setSwitchNote(
        response.data.accepted
          ? `${t.system.switchDone} ${response.data.note_ar}`
          : t.system.switchFailed,
      );
      // الحالة تُقرأ من الخادم بعد التبديل، ولا تُخمَّن محلياً: البطاقة أعلاه
      // تعرض البيئة، وتخمينُها هنا يجعل شاشتين تختلفان على نفس الحقيقة.
      refresh();
    } catch (caught) {
      setSwitchOk(false);
      setSwitchNote(
        caught instanceof ApiError ? caught.messageAr : t.system.switchFailed,
      );
    } finally {
      setSwitching(false);
    }
  };

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
            {data.broker.note_ar !== null ? (
              <Field label="السبب" value={data.broker.note_ar} tone="caution" />
            ) : null}
            <Field label={t.system.accountMasked} value={data.broker.account_masked} />
            <Field
              label={t.system.executionLock}
              value={data.broker.execution_locked ? t.system.locked : t.system.unlocked}
              tone={data.broker.execution_locked ? 'positive' : 'caution'}
              hint="قفل التنفيذ يُدار على الخادم ولا يُفتح من الهاتف."
            />
          </Card>

          {/*
            التبديل تحت بطاقة الوسيط مباشرةً: القرار يُتخذ وأنت تنظر إلى
            الحساب الحالي، لا في شاشةٍ أخرى تُقرأ من الذاكرة.
          */}
          <Card testID="environment-card" title={t.system.switchTitle}>
            <Text variant="caption" tone="secondary">
              {t.system.switchBody}
            </Text>
            {switchNote !== null ? (
              <Banner
                testID="environment-result"
                tone={switchOk ? 'positive' : 'negative'}
                title={switchNote}
              />
            ) : null}
            {data.broker.is_demo ? (
              <ConfirmButton
                testID="switch-to-live"
                label={t.system.switchToLive}
                tone="caution"
                busy={switching}
                accessibilityLabel={t.system.switchToLive}
                accessibilityHint={t.system.switchToLiveConfirmBody}
                confirmTitle={t.system.switchToLiveConfirmTitle}
                confirmBody={t.system.switchToLiveConfirmBody}
                confirmLabel={t.system.switchToLiveConfirm}
                onConfirm={() => {
                  void switchTo('LIVE');
                }}
              />
            ) : (
              <ConfirmButton
                testID="switch-to-demo"
                label={t.system.switchToDemo}
                tone="neutral"
                busy={switching}
                accessibilityLabel={t.system.switchToDemo}
                accessibilityHint={t.system.switchToDemoBody}
                confirmTitle={t.system.switchToDemo}
                confirmBody={t.system.switchToDemoBody}
                confirmLabel={t.system.switchToDemoConfirm}
                onConfirm={() => {
                  void switchTo('DEMO');
                }}
              />
            )}
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
