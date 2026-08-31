import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  ErrorState,
  Field,
  Hadd,
  LoadingState,
  Metric,
  Screen,
  StatusPill,
  Text,
  Vacancy,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentDecision, presentStage } from '@/utils/present';

/**
 * تفصيل القرار.
 *
 * الامتناع يُعرض بوصفه **قراراً مكتملاً**، لا نقصاً ولا فشلاً. لذلك تُعرض
 * أسباب المنع كاملةً بترتيب الخادم، ولا يُخفى أيّها ولا يُلخَّص.
 */
export default function DecisionScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getDecision(), {
    previewData: previewOr(fixtures.decision),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.decision.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.decision.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const presented = presentDecision(data.decision, data.decision_ar);

  return (
    <Screen
      testID="decision-screen"
      title={t.decision.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Card testID="final-decision-card" title={t.decision.finalDecision}>
        <StatusPill
          testID="final-decision-pill"
          label={presented.labelAr}
          tone={presented.tone}
          accessibilityLabel={`${t.decision.finalDecision}: ${presented.labelAr}`}
        />
        <View style={{ flexDirection: 'row', gap: theme.spacing.xl }}>
          <Metric
            testID="decision-score"
            label="النتيجة الحتمية"
            value={data.score === null ? null : `${data.score.total}`}
            caption={data.score === null ? undefined : `من ${data.score.max}`}
          />
        </View>
        {data.score !== null && data.score.max > 0 ? (
          <Hadd
            testID="decision-score-hadd"
            value={data.score.total}
            max={data.score.max}
            label={t.decision.scoreSpan}
            readout={`${data.score.total} / ${data.score.max}`}
            style={{ marginTop: theme.spacing.xs }}
          />
        ) : null}
        <Divider />
        <Field label={t.decision.reasonCode} value={data.reason_code} />
        <Field label={t.decision.snapshot} value={data.snapshot_id} />
        <Field label={t.decision.decidedAt} value={formatInstant(data.decided_at_utc)} />
      </Card>

      {data.explanation_ar !== null ? (
        <Card testID="decision-explanation-card" title="الشرح">
          <Text variant="body">{data.explanation_ar}</Text>
        </Card>
      ) : null}

      <Card testID="blocking-card" title={t.decision.blocking}>
        {data.blocking_reasons_ar.length === 0 ? (
          <Vacancy
            testID="no-blocking-empty"
            what={t.decision.noBlockingWhat}
            why={t.decision.noBlockingWhy}
          />
        ) : (
          data.blocking_reasons_ar.map((reason, index) => (
            <View
              key={`${index}-${reason}`}
              accessible
              accessibilityRole="text"
              accessibilityLabel={`سبب منع ${index + 1}: ${reason}`}
              style={{ flexDirection: 'row', gap: theme.spacing.sm }}
            >
              <Text variant="captionStrong" tone="caution">
                {`${index + 1}.`}
              </Text>
              <Text variant="caption" tone="secondary" style={{ flex: 1 }}>
                {reason}
              </Text>
            </View>
          ))
        )}
      </Card>

      <Card testID="decision-stages-card" title={t.decision.stages}>
        {data.stages.length === 0 ? (
          <Vacancy
            testID="decision-stages-empty"
            what={t.intelligence.stagesEmptyWhat}
            why={t.intelligence.stagesEmptyWhy}
          />
        ) : (
          data.stages.map((stage, index) => (
            <View key={stage.stage} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <View
                style={{
                  flexDirection: 'row',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: theme.spacing.sm,
                }}
                accessible
                accessibilityRole="text"
                accessibilityLabel={`${stage.name_ar}: ${presentStage(stage.passed).labelAr}`}
              >
                <Text variant="body" style={{ flex: 1 }}>
                  {stage.name_ar}
                </Text>
                <StatusPill
                  label={presentStage(stage.passed).labelAr}
                  tone={presentStage(stage.passed).tone}
                />
              </View>
            </View>
          ))
        )}
      </Card>

      <Banner
        testID="descriptive-only-banner"
        tone="info"
        title={t.common.readOnly}
        body={t.decision.descriptiveOnly}
      />
    </Screen>
  );
}
