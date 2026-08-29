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
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatCooling, formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';

/**
 * ملفات المخاطرة — **عرض فقط**.
 *
 * لا يوجد على هذه الشاشة زر اختيار ولا تبديل. رفع المخاطرة إجراء يزيدها،
 * والهاتف لا يزيد شيئاً: التغيير يتم على الخادم وبتبريد مفروض هناك، ولا يستطيع
 * التطبيق تقصيره ولا تجاوزه.
 */
export default function ProfilesScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getProfiles(), {
    previewData: previewOr(fixtures.profiles),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.profiles.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.profiles.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="profiles-screen"
      title={t.profiles.title}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      <Banner
        testID="profiles-readonly-banner"
        tone="info"
        title={t.common.readOnly}
        body={t.profiles.cannotChange}
      />

      <Card testID="current-profile-card" title="الحالي">
        <Field label={t.profiles.selected} value={data.selected_name_ar ?? data.selected_profile} />
        <Field
          label={t.profiles.effective}
          value={data.effective_name_ar ?? data.effective_profile}
          hint={data.risk_level_ar ?? undefined}
        />
        {data.pending_profile !== null ? (
          <>
            <Divider />
            <Field label={t.profiles.pending} value={data.pending_profile} tone="caution" />
            <Field
              label={t.profiles.coolingRemaining}
              value={formatCooling(data.cooling_remaining_seconds)}
              hint={
                data.pending_available_at_utc === null
                  ? undefined
                  : formatInstant(data.pending_available_at_utc)
              }
              tone="caution"
            />
          </>
        ) : null}
        {data.change_blocked_reason_ar !== null ? (
          <Field label={t.profiles.blocked} value={data.change_blocked_reason_ar} tone="caution" />
        ) : null}
        <Field label="بصمة الدستور" value={data.fingerprint} />
      </Card>

      <Card testID="available-profiles-card" title={t.profiles.available}>
        {data.available_profiles.map((profile, index) => {
          const isEffective = profile.profile === data.effective_profile;
          return (
            <View key={profile.profile} style={{ gap: theme.spacing.sm }}>
              {index > 0 ? <Divider /> : null}
              <View
                accessible
                accessibilityRole="text"
                accessibilityLabel={`${profile.name_ar}. ${profile.description_ar}. ${
                  isEffective ? 'الملف الفعّال.' : ''
                }`}
                style={{
                  flexDirection: 'row',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: theme.spacing.sm,
                }}
              >
                <Text variant="bodyStrong" style={{ flex: 1 }}>
                  {profile.name_ar}
                </Text>
                {isEffective ? <StatusPill label="الفعّال" tone="accent" /> : null}
              </View>
              <Text variant="caption" tone="secondary">
                {profile.description_ar}
              </Text>
              <Field label={t.profiles.riskRank} value={profile.risk_rank} />
              <Field label="أقصى مخاطرة للصفقة" value={profile.limits.max_risk_per_trade} />
              <Field label="أقصى خسارة يومية" value={profile.limits.max_daily_loss} />
              <Field label="أقصى خسارة أسبوعية" value={profile.limits.max_weekly_loss} />
              <Field label="حد التراجع التشغيلي" value={profile.limits.operational_drawdown_stop} />
              <Field label="الحد المطلق للخسارة" value={profile.limits.absolute_loss_boundary} />
              <Field label="أقصى مراكز مفتوحة" value={profile.limits.max_open_positions} />
              <Field label="أقصى دخول في اليوم" value={profile.limits.max_entry_orders_per_day} />
              <Field label="أدنى عائد/مخاطرة صافٍ" value={profile.limits.min_net_reward_risk} />
              <Field label="أدنى نتيجة جودة" value={profile.limits.min_quality_score} />
              <Field
                label="المبيت"
                value={profile.limits.allow_overnight ? t.common.yes : t.common.no}
              />
              <Field
                label="الاحتفاظ في العطلة"
                value={profile.limits.allow_weekend_hold ? t.common.yes : t.common.no}
              />
            </View>
          );
        })}
      </Card>
    </Screen>
  );
}
