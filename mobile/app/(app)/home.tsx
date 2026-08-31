import React, { useCallback } from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import { ApiError } from '@/api/client';
import {
  AnimatedNumber,
  Banner,
  Card,
  Divider,
  ErrorState,
  Field,
  LoadingState,
  NavRow,
  OfflineBanner,
  RiskMeter,
  Screen,
  StaleBanner,
  StatusPill,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatCooling, formatInstant, formatRatio, formatSince, t } from '@/i18n';
import { useTheme } from '@/theme';
import {
  presentCompleteness,
  presentConnection,
  presentDecision,
  presentMarket,
  presentPnlTone,
  presentSystemPhase,
} from '@/utils/present';

/**
 * لوحة الرئيسية.
 *
 * ## لماذا أُعيد ترتيبها
 *
 * كانت **تسع بطاقات متساوية الوزن** فوق بعضها، فلا شيء فيها أهمّ من شيء —
 * والشاشة التي كل شيء فيها مهمّ لا شيء فيها مهمّ. وقياس 69 لقطة من 18 تطبيقاً
 * وجد أن **لا واحد منها يعرض «لماذا لم أتداول»**. فهذا هو الفراغ، وهذا موضعه:
 * أول ما تقع عليه العين، بحجم العنوان لا بحجم الحاشية.
 *
 * الترتيب الآن يجيب أسئلة بترتيب طرحها:
 *   1. ماذا قرّرتَ اليوم، ولماذا؟   ← الحكم، بحجم العنوان
 *   2. كم بقي لي؟                  ← المتبقّي رقماً كبيراً متحرّكاً
 *   3. هل النظام بخير؟             ← شريط حالة مضغوط
 *   4. التفاصيل                    ← تحت، لمن أرادها
 *
 * وبطاقة «الشاشات» حُذفت: كانت قائمة تنقّل مرسومة كبطاقة، وحلّ محلّها شريط
 * التبويبات أسفل الشاشة.
 *
 * كل قيمة معروضة تأتي من الخادم. ما لم يصل يُقال «غير متاح» ولا يُخترع.
 */
export default function HomeScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();

  const status = useEndpoint((c) => c.getStatus(), { previewData: previewOr(fixtures.status) });
  const decision = useEndpoint((c) => c.getDecision(), {
    previewData: previewOr(fixtures.decision),
  });
  const risk = useEndpoint((c) => c.getRisk(), { previewData: previewOr(fixtures.risk) });
  const profiles = useEndpoint((c) => c.getProfiles(), {
    previewData: previewOr(fixtures.profiles),
  });
  const position = useEndpoint((c) => c.getCurrentPosition(), {
    previewData: previewOr(fixtures.position),
  });

  const refreshAll = useCallback(() => {
    status.refresh();
    decision.refresh();
    risk.refresh();
    profiles.refresh();
    position.refresh();
  }, [status, decision, risk, profiles, position]);

  const offline =
    status.error instanceof ApiError && status.error.kind === 'OFFLINE';
  const anyLoading = status.loading && status.data === null;

  const s = status.data;
  const d = decision.data;
  const r = risk.data;
  const p = profiles.data;
  const pos = position.data;

  /** المتبقّي رقماً — للعدّ المتدرّج. نصٌّ غير قابل للتحويل ⇒ `null` بلا تخمين. */
  const remainingToday = ((): number | null => {
    const v = Number(r?.risk_remaining_today?.replace(/,/g, ''));
    return Number.isFinite(v) ? v : null;
  })();

  /** الربح غير المحقّق رقماً. نصٌّ غير قابل للتحويل ⇒ يُعرض كما هو بلا حركة. */
  const unrealised = ((): number | null => {
    const v = Number(pos?.unrealised_pnl?.replace(/[,\s+]/g, '').replace('−', '-'));
    return Number.isFinite(v) ? v : null;
  })();

  const riskRatio = ((): number | null => {
    if (r === null) {
      return null;
    }
    const used = Number(r.risk_used_today?.replace(/,/g, ''));
    const remaining = Number(r.risk_remaining_today?.replace(/,/g, ''));
    if (!Number.isFinite(used) || !Number.isFinite(remaining)) {
      return null;
    }
    const total = used + remaining;
    return total > 0 ? used / total : null;
  })();

  return (
    <Screen
      testID="home-screen"
      title={t.home.title}
      subtitle={t.app.tagline}
      preview={preview}
      onRefresh={refreshAll}
      refreshing={status.loading}
    >
      {offline ? <OfflineBanner /> : null}
      {!offline && status.stale ? (
        <StaleBanner sinceLabel={formatSince(s?.last_refresh_utc ?? null)} />
      ) : null}

      {anyLoading ? <LoadingState /> : null}

      {status.error !== null && s === null ? (
        <ErrorState error={status.error} onRetry={refreshAll} />
      ) : null}

      {/* ---- الحكم: أول ما تقع عليه العين ---- */}
      {s !== null || d !== null ? (
        <View style={{ gap: theme.spacing.sm, paddingBottom: theme.spacing.xs }}>
          <Text variant="micro" tone="tertiary">
            اليوم
          </Text>
          <Text variant="display" testID="home-verdict">
            {d !== null && d.decision !== 'NO_TRADE'
              ? presentDecision(d.decision, d.decision_ar).labelAr
              : 'لم أتداول'}
          </Text>
          {s !== null && s.no_trade_reason_ar !== null ? (
            <Text variant="body" tone="secondary" testID="no-trade-reason">
              {s.no_trade_reason_ar}
            </Text>
          ) : d !== null && d.explanation_ar !== null ? (
            <Text variant="body" tone="secondary" testID="decision-explanation">
              {d.explanation_ar}
            </Text>
          ) : null}
          {d?.blocking_reasons_ar.map((reason, index) => (
            <View
              key={`${index}-${reason}`}
              style={{ flexDirection: 'row', gap: theme.spacing.sm }}
              accessible
              accessibilityRole="text"
              accessibilityLabel={reason}
            >
              <Text variant="caption" tone="tertiary">
                ·
              </Text>
              <Text variant="caption" tone="secondary" style={{ flex: 1 }}>
                {reason}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* ---- كم بقي لي ---- */}
      {r !== null ? (
        <Card testID="risk-card" title={t.home.risk}>
          <RiskMeter
            testID="risk-meter-daily"
            label="المتبقّي من مخاطرة اليوم"
            usedLabel={r.risk_used_today}
            remainingLabel={r.risk_remaining_today}
            remainingValue={remainingToday}
            ratio={riskRatio}
          />
          {r.two_loss_lock_active ? (
            <Banner tone="negative" title="قفل الخسارتين مُفعَّل" body="لا دخول جديد اليوم." />
          ) : null}
        </Card>
      ) : null}

      {/* ---- حالة النظام ---- */}
      {s !== null ? (
        <Card testID="system-card" title={t.home.systemState}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <StatusPill
              testID="system-state-pill"
              label={presentSystemPhase(s.system_state, s.system_state_ar).labelAr}
              tone={presentSystemPhase(s.system_state, s.system_state_ar).tone}
            />
            {s.kill_switch.active ? (
              <StatusPill testID="killswitch-pill" label="قاطع الطوارئ مُفعَّل" tone="negative" />
            ) : null}
            {/* الشارة الثانية تظهر فقط إن لم تقلها المرحلة — كانت تُعرض مرّتين. */}
            {s.locally_paused &&
            !presentSystemPhase(s.system_state, s.system_state_ar).labelAr.includes('موقوف') ? (
              <StatusPill testID="paused-pill" label="موقوف محلياً" tone="caution" />
            ) : null}
          </View>

          <Divider />

          <Field
            testID="broker-field"
            label={t.home.brokerConnection}
            value={`${s.broker.name} — ${presentConnection(s.broker.connected).labelAr}`}
            tone={s.broker.connected ? 'positive' : 'negative'}
            hint={s.broker.is_demo ? t.system.demo : t.system.live}
          />
          <Field
            testID="market-field"
            label={t.home.marketStatus}
            value={presentMarket(s.market.is_open).labelAr}
            hint={s.market.reason_ar}
          />
          <Field
            testID="completeness-field"
            label={t.home.completeness}
            value={`${presentCompleteness(
              s.data_completeness.complete,
              s.data_completeness.missing.length,
            ).labelAr} · ${formatRatio(s.data_completeness.ratio)}`}
            tone={s.data_completeness.complete ? 'positive' : 'caution'}
            hint={
              s.data_completeness.missing.length > 0
                ? s.data_completeness.missing.join('، ')
                : undefined
            }
          />
          <Field
            testID="last-refresh-field"
            label={t.common.lastRefresh}
            value={formatSince(s.last_refresh_utc)}
            hint={formatInstant(s.last_refresh_utc)}
          />
        </Card>
      ) : null}

      {/* ---- تفاصيل الأسبوع ---- */}
      {r !== null ? (
        <Card testID="risk-week-card" title="الأسبوع">
          <Field label="المستهلَك" value={r.risk_used_week} />
          <Field label="المتبقّي" value={r.risk_remaining_week} />
          <Field
            label="المسافة إلى قاطع الطوارئ"
            value={r.distance_to_kill_switch}
            tone="caution"
          />
        </Card>
      ) : null}

      {/* ---- الملف ---- */}
      {p !== null ? (
        <Card testID="profile-card" title={t.home.profile}>
          <Field label={t.profiles.selected} value={p.selected_name_ar ?? p.selected_profile} />
          <Field label={t.profiles.effective} value={p.effective_name_ar ?? p.effective_profile} />
          {p.pending_profile !== null ? (
            <Field
              label={t.profiles.pending}
              value={p.pending_profile}
              hint={`${t.profiles.coolingRemaining}: ${formatCooling(
                p.cooling_remaining_seconds,
              )}`}
              tone="caution"
            />
          ) : null}
          <NavRow
            testID="nav-profiles"
            label={t.nav.profiles}
            hint={t.profiles.cannotChange}
            href="/(app)/profiles"
          />
        </Card>
      ) : null}

      {/* ---- القرار ---- */}
      {d !== null ? (
        <Card testID="decision-card" title={t.home.decision}>
          <StatusPill
            testID="decision-pill"
            label={presentDecision(d.decision, d.decision_ar).labelAr}
            tone={presentDecision(d.decision, d.decision_ar).tone}
          />
          <Field
            testID="score-field"
            label={t.home.score}
            value={d.score === null ? null : `${d.score.total} / ${d.score.max}`}
            large
          />
          <NavRow
            testID="nav-decision"
            label={t.nav.decision}
            hint={t.decision.descriptiveOnly}
            href="/(app)/decision"
          />
        </Card>
      ) : null}

      {/* ---- الاستراتيجية ---- */}
      {s !== null && s.strategy_state !== null ? (
        <Card testID="strategy-card" title={t.home.strategy}>
          <Field label="الاستراتيجية" value={s.strategy_state.title_ar} />
          <Field
            label="الحالة"
            value={s.strategy_state.state}
            tone={s.strategy_state.live_eligible ? 'positive' : 'caution'}
            hint={
              s.strategy_state.live_eligible
                ? 'مُجازة للتنفيذ على الخادم.'
                : 'غير مُجازة للتنفيذ بعد.'
            }
          />
        </Card>
      ) : null}

      {/* ---- الحدث القادم ---- */}
      <Card testID="event-card" title={t.home.upcomingEvent}>
        {s !== null && s.upcoming_event !== null ? (
          <>
            <Field label="الحدث" value={s.upcoming_event.title_ar} />
            <Field
              label="الوقت"
              value={formatInstant(s.upcoming_event.at_utc)}
              hint={s.upcoming_event.impact_ar}
              tone={s.upcoming_event.blocks_trading ? 'caution' : 'primary'}
            />
          </>
        ) : (
          <Text variant="caption" tone="tertiary" testID="no-event">
            {t.home.noEvent}
          </Text>
        )}
      </Card>

      {/* ---- المركز الحالي ---- */}
      <Card testID="position-card" title={t.home.position}>
        {pos !== null && pos.has_position ? (
          <>
            <Field label={t.position.instrument} value={pos.instrument_ar ?? pos.instrument} />
            <Field label={t.position.direction} value={pos.direction_ar} />
            {/*
              الربح غير المحقّق: الرقم الوحيد في التطبيق الذي يتحرّك لحظياً.
              يأخذ الإشارة `+` أو `−` مع اللون — فاللون يعطي السرعة، والإشارة
              تضمن أن المعنى لا يضيع في التدرّج الرمادي ولا عند عمى الألوان.
            */}
            <View style={{ gap: theme.spacing.xs }}>
              <Text variant="caption" tone="secondary">
                {t.position.unrealised}
              </Text>
              {unrealised !== null ? (
                <AnimatedNumber
                  value={unrealised}
                  decimals={2}
                  unit="دولار"
                  variant="numericLarge"
                  signed
                  testID="unrealised-pnl"
                />
              ) : (
                <Text
                  variant="numericLarge"
                  tone={presentPnlTone(pos.unrealised_pnl_sign)}
                  tabular
                  testID="unrealised-pnl"
                >
                  {pos.unrealised_pnl ?? '—'}
                </Text>
              )}
            </View>
            <NavRow
              testID="nav-position"
              label={t.nav.position}
              hint={t.position.cannotModify}
              href="/(app)/position"
            />
          </>
        ) : (
          <Text variant="caption" tone="tertiary" testID="no-position">
            {t.home.noPosition}
          </Text>
        )}
      </Card>

      {/* التنقّل صار في شريط التبويبات أسفل الشاشة — لا قائمةً مرسومة كبطاقة. */}

      <Text variant="micro" tone="tertiary" testID="home-no-execution">
        {t.common.noExecution}
      </Text>
    </Screen>
  );
}
