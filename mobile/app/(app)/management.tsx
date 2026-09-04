import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
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
  Vacancy,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * إدارةُ المراكز بعد الفتح.
 *
 * ## لماذا تعرض «ما لم يُفعَل» بنفس بروز «ما فُعل»
 *
 * شاشةٌ تعرض الأفعال وحدها تجيب عن السؤال السهل. والسؤال الذي يقلق المالكة —
 * وقد سألته فعلاً — هو: **لماذا لم يتحرّك شيء؟** فكلُّ مركزٍ مُتخطّى يظهر
 * بسببه المُصنَّف، وكلُّ سياسةٍ معلَنة تظهر بقدراتها وإصدارها.
 *
 * والحقيقةُ اليوم صريحة على الشاشة: لا سياسةَ ديناميكيةٍ مفعّلة، لأنّ الدليل
 * شرطُ التفعيل ولا دليلَ لواحدة. وذلك أصدق من قواعد تُطبَّق لأنها «معقولة».
 */
export default function ManagementScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getManagement(), {
    previewData: previewOr(fixtures.management),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.management.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.management.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const syncFailed = data.sync !== undefined && data.sync !== null && !data.sync.ok;

  return (
    <Screen
      testID="management-screen"
      title={t.management.title}
      subtitle={data.plan_at_utc === null ? undefined : formatInstant(data.plan_at_utc)}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {syncFailed ? (
        <Banner
          testID="management-sync-failed"
          tone="caution"
          title={t.management.syncFailed}
          body={data.sync.error_ar ?? ''}
        />
      ) : null}

      {!data.dynamic_enabled ? (
        <Banner
          testID="management-fixed-only"
          tone="info"
          title={t.management.fixedOnlyTitle}
          body={t.management.fixedOnlyBody}
        />
      ) : null}

      <Card testID="management-summary">
        <Field label={t.management.actionCount} value={String(data.action_count ?? '—')} />
        <Field
          label={t.management.dynamic}
          value={data.dynamic_enabled ? t.management.on : t.management.off}
          tone={data.dynamic_enabled ? 'caution' : 'positive'}
        />
        <Field label={t.management.policyCount} value={String(data.declared_policies.length)} />
      </Card>

      <Card testID="management-actions">
        <Text variant="bodyStrong">{t.management.actionsTitle}</Text>
        {data.actions.length === 0 ? (
          <Vacancy testID="management-no-actions" what={t.management.noActions} />
        ) : (
          data.actions.map((action, index) => (
            <View key={action.deal_id ?? String(index)} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <View style={{ flexDirection: 'row', gap: theme.spacing.sm, alignItems: 'center' }}>
                <StatusPill label={action.kind_ar ?? '—'} tone="accent" />
                <Text variant="bodyStrong">{action.symbol ?? '—'}</Text>
              </View>
              {/* القيمتان معاً: سجلٌّ بلا القيمة القديمة لا يُراجَع. */}
              <Field
                label={t.management.change}
                value={`${action.old_value ?? '—'} ← ${action.new_value ?? '—'}`}
              />
              <Field
                label={t.management.policy}
                value={`${action.policy_version ?? '—'} · ${action.strategy ?? '—'}@${
                  action.strategy_version ?? '—'
                }`}
              />
              <Text variant="caption" tone="secondary">
                {action.reason_ar ?? ''}
              </Text>
            </View>
          ))
        )}
      </Card>

      <Card testID="management-skipped">
        <Text variant="bodyStrong">{t.management.skippedTitle}</Text>
        <Text variant="caption" tone="secondary">
          {t.management.skippedNote}
        </Text>
        {data.skipped.length === 0 ? (
          <Vacancy testID="management-no-skips" what={t.management.noSkips} />
        ) : (
          data.skipped.map((skip, index) => (
            <View key={`${skip.deal_id ?? index}`} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <Field label={skip.symbol ?? '—'} value={skip.code_ar ?? skip.code ?? '—'} />
              <Text variant="caption" tone="secondary">
                {skip.reason_ar ?? ''}
              </Text>
            </View>
          ))
        )}
      </Card>

      <Card testID="management-policies">
        <Text variant="bodyStrong">{t.management.policiesTitle}</Text>
        {data.declared_policies.length === 0 ? (
          <Vacancy testID="management-no-policies" what={t.management.noPolicies} />
        ) : (
          data.declared_policies.map((policy, index) => (
            <View key={`${policy.strategy ?? index}`} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <Field
                label={`${policy.strategy ?? '—'}@${policy.strategy_version ?? '—'}`}
                value={policy.policy_version ?? '—'}
              />
              <Text variant="caption" tone="secondary">
                {policy.capabilities.join(' · ')}
              </Text>
            </View>
          ))
        )}
      </Card>

      {data.notes_ar.map((note, index) => (
        <Text key={index} variant="caption" tone="tertiary">
          {note}
        </Text>
      ))}
    </Screen>
  );
}
