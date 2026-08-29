import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  EmptyState,
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
import { presentProvider } from '@/utils/present';

/**
 * صحة المزوّدين.
 *
 * الشاشة تعرض **الحالة لا الاعتماد**: اسم المزوّد وهل هو مُعدّ وهل يستجيب.
 * لا يظهر هنا مفتاح ولا جزء من مفتاح ولا حتى طوله — المفاتيح كلها على الخادم،
 * وهذا التطبيق لا يملك منها شيئاً يعرضه.
 */
export default function ProvidersScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getProviderHealth(), {
    previewData: previewOr(fixtures.providers),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.providers.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.providers.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="providers-screen"
      title={t.providers.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {data.missing_mandatory.length > 0 ? (
        <Banner
          testID="missing-mandatory-banner"
          tone="negative"
          title={t.providers.missingMandatory}
          body={data.missing_mandatory.join('، ')}
        />
      ) : null}

      <Card testID="eligibility-card">
        <Field
          label={t.providers.eligibility}
          value={data.live_eligible_by_providers ? 'مستوفاة' : 'غير مستوفاة'}
          tone={data.live_eligible_by_providers ? 'positive' : 'caution'}
        />
      </Card>

      <Card testID="providers-card" title="المزوّدون">
        {data.providers.length === 0 ? (
          <EmptyState message={t.common.notComputed} />
        ) : (
          data.providers.map((provider, index) => {
            const presented = presentProvider(provider.configured, provider.healthy);
            return (
              <View key={`${provider.kind}-${provider.name}`} style={{ gap: theme.spacing.xs }}>
                {index > 0 ? <Divider /> : null}
                <View
                  accessible
                  accessibilityRole="text"
                  accessibilityLabel={`${provider.name_ar ?? provider.name}. ${
                    presented.labelAr
                  }. ${provider.mandatory ? t.providers.mandatory : ''}. ${provider.note_ar}`}
                  style={{
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: theme.spacing.sm,
                  }}
                >
                  <Text variant="bodyStrong" style={{ flex: 1 }}>
                    {provider.name_ar ?? provider.name}
                  </Text>
                  <StatusPill label={presented.labelAr} tone={presented.tone} />
                </View>
                {provider.mandatory ? (
                  <Text variant="micro" tone="caution">
                    {t.providers.mandatory}
                  </Text>
                ) : null}
                <Field
                  label={t.providers.lastSuccess}
                  value={formatInstant(provider.last_success_utc)}
                />
                <Text variant="caption" tone="secondary">
                  {provider.note_ar}
                </Text>
              </View>
            );
          })
        )}
      </Card>
    </Screen>
  );
}
