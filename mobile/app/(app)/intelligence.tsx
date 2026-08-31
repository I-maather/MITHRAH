import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Card,
  Divider,
  Vacancy,
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
import { presentStage } from '@/utils/present';

/**
 * قراءة السوق.
 *
 * الشاشة تعرض **مصدر كل سطر**: كل بند في النتيجة يحمل من أين جاء، وكل مرحلة
 * تقول أهي إلزامية أم لا. رقمٌ بلا مصدر لا يُعرض هنا.
 */
export default function IntelligenceScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getIntelligence(), {
    previewData: previewOr(fixtures.intelligence),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.intelligence.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.intelligence.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  if (!data.available) {
    return (
      <Screen title={t.intelligence.title} preview={preview} onRefresh={refresh}>
        <Vacancy
          testID="intelligence-unavailable"
          tone="waiting"
          what={data.reason_ar ?? t.intelligence.unavailable}
          why={t.intelligence.unavailableWhy}
          next={t.intelligence.unavailableNext}
        />
      </Screen>
    );
  }

  return (
    <Screen
      testID="intelligence-screen"
      title={t.intelligence.title}
      subtitle={
        data.decided_at_utc === null ? undefined : formatInstant(data.decided_at_utc)
      }
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {data.regime !== null ? (
        <Card testID="regime-card" title={t.intelligence.regime}>
          <StatusPill
            label={data.regime.name_ar}
            tone={data.regime.tradable ? 'positive' : 'caution'}
          />
          <Text variant="caption" tone="secondary">
            {data.regime.reason_ar}
          </Text>
        </Card>
      ) : null}

      {data.timeframes !== null ? (
        <Card testID="timeframes-card" title={t.intelligence.timeframes}>
          <Field label="اتجاه إطار النظام" value={data.timeframes.primary_regime_trend} />
          <Field label="الاتجاه البنيوي" value={data.timeframes.structural_trend} />
          <Field label="اتجاه إطار الدخول" value={data.timeframes.entry_trend} />
          {data.timeframes.incomplete.length > 0 ? (
            <Field
              label="أطر ناقصة"
              value={data.timeframes.incomplete.join('، ')}
              tone="caution"
            />
          ) : null}
        </Card>
      ) : null}

      <Card testID="stages-card" title={t.intelligence.stages}>
        {data.stages.length === 0 ? (
          <Vacancy
            testID="intelligence-stages-empty"
            what={t.intelligence.stagesEmptyWhat}
            why={t.intelligence.stagesEmptyWhy}
          />
        ) : (
          data.stages.map((stage, index) => (
            <View key={stage.stage} style={{ gap: theme.spacing.sm }}>
              {index > 0 ? <Divider /> : null}
              <View
                accessible
                accessibilityRole="text"
                accessibilityLabel={`${stage.name_ar}. ${
                  presentStage(stage.passed).labelAr
                }. ${stage.mandatory ? t.intelligence.mandatory : t.intelligence.optional}. ${
                  stage.detail_ar ?? ''
                }`}
                style={{ gap: theme.spacing.xs }}
              >
                <View
                  style={{
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: theme.spacing.sm,
                  }}
                >
                  <Text variant="bodyStrong" style={{ flex: 1 }}>
                    {stage.name_ar}
                  </Text>
                  <StatusPill
                    label={presentStage(stage.passed).labelAr}
                    tone={presentStage(stage.passed).tone}
                  />
                </View>
                <Text variant="micro" tone="tertiary">
                  {stage.mandatory ? t.intelligence.mandatory : t.intelligence.optional}
                </Text>
                {stage.detail_ar !== null ? (
                  <Text variant="caption" tone="secondary">
                    {stage.detail_ar}
                  </Text>
                ) : null}
              </View>
            </View>
          ))
        )}
      </Card>

      {data.score !== null ? (
        <Card
          testID="score-card"
          title={t.intelligence.score}
          subtitle={`${data.score.total} / ${data.score.max}`}
        >
          {data.score.has_mandatory_failure ? (
            <View style={{ gap: theme.spacing.sm }}>
              {data.score.mandatory_failures.map((failure) => (
                <View
                  key={failure.code}
                  accessible
                  accessibilityRole="text"
                  accessibilityLabel={`إخفاق إلزامي: ${failure.reason_ar}`}
                  style={{ gap: 2 }}
                >
                  <Text variant="captionStrong" tone="negative">
                    {failure.code}
                  </Text>
                  <Text variant="caption" tone="secondary">
                    {failure.reason_ar}
                  </Text>
                </View>
              ))}
              <Divider />
            </View>
          ) : null}

          {data.score.lines.map((line) => (
            <View key={line.category} style={{ gap: 2 }}>
              <Field
                label={line.category_ar}
                value={`${line.awarded} / ${line.maximum}`}
                hint={line.reason_ar}
              />
              <Text variant="micro" tone="tertiary">
                {`المصدر: ${line.source_ar}`}
              </Text>
            </View>
          ))}
        </Card>
      ) : null}

      {data.contradictions !== null && data.contradictions.count > 0 ? (
        <Card
          testID="contradictions-card"
          title={t.intelligence.contradictions}
          subtitle={`${data.contradictions.count}`}
        >
          {data.contradictions.items.map((item, index) => (
            <View key={`${item.kind}-${index}`} style={{ gap: theme.spacing.xs }}>
              {index > 0 ? <Divider /> : null}
              <Text variant="bodyStrong">{item.kind}</Text>
              <Text variant="caption" tone="secondary">{`أ: ${item.side_a_ar}`}</Text>
              <Text variant="caption" tone="secondary">{`ب: ${item.side_b_ar}`}</Text>
              <Text variant="caption" tone="secondary">{item.resolution_ar}</Text>
              {item.blocks_trading ? (
                <StatusPill label={t.intelligence.blocksTrading} tone="negative" />
              ) : null}
            </View>
          ))}
        </Card>
      ) : null}

      {data.missing_providers.length > 0 || data.missing_data.length > 0 ? (
        <Card testID="missing-card" title="ما هو ناقص">
          {data.missing_providers.length > 0 ? (
            <Field
              label={t.intelligence.missingProviders}
              value={data.missing_providers.join('، ')}
              tone="caution"
            />
          ) : null}
          {data.missing_data.length > 0 ? (
            <Field
              label={t.intelligence.missingData}
              value={data.missing_data.join('، ')}
              tone="caution"
            />
          ) : null}
        </Card>
      ) : null}

      {data.explanation_ar !== null ? (
        <Card testID="explanation-card" title={t.intelligence.explanation}>
          <Text variant="body">{data.explanation_ar}</Text>
        </Card>
      ) : null}

      <Text variant="micro" tone="tertiary">
        {t.common.noExecution}
      </Text>
    </Screen>
  );
}
