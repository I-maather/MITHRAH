import React, { useState } from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  APP_VERSION,
  BUILD_COMMIT,
  BUILD_NUMBER,
  BUILD_TIME,
  BUNDLE_IDENTIFIER,
  TRADING_ENVIRONMENT,
} from '@/api/config';
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
  NavRow,
  Screen,
  StatusPill,
  Text,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatCooling, formatInstant, formatRatio, formatSince, t } from '@/i18n';
import { useTheme } from '@/theme';
import {
  presentCompleteness,
  presentConnection,
  presentMarket,
  presentSystemPhase,
} from '@/utils/present';

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
  /*
    **رصيدُ الوسيط نزل من «اليوم» إلى هنا.**

    القرارُ المعتمد أنّ الحصّة المخصَّصة هي المقياس، ورصيدَ الوسيط معلومةُ
    كفايةِ هامشٍ لا مقياس. وعرضُهما ندّين في رأس «اليوم» كان يقلب المعنى.
  */
  const risk = useEndpoint((c) => c.getRisk(), { previewData: previewOr(fixtures.risk) });
  const profiles = useEndpoint((c) => c.getProfiles(), {
    previewData: previewOr(fixtures.profiles),
  });
  const r = risk.data;
  const p = profiles.data;
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
      {/* ----------------------------------------------------------------
          **حالةُ التشغيل في بطاقةٍ واحدة.**

          كانت مبعثرة: القاطعُ في أسفل هذه الشاشة، والخدمةُ والإيقاف في
          «اليوم». وسؤالُ «هل الوكيل سليم؟» يُجاب بنظرةٍ واحدة أو لا يُجاب.

          ولا يُكتب هنا سطرٌ عن «مراقبة المراكز» لأنّ العقد لا يحمل له
          حقلاً — يُقال بدلَه ما هو صحيحٌ ومعروف: أنّ الإيقاف يمنع الدخول
          وحده. جملةُ تصميمٍ صادقة خيرٌ من قراءةٍ مخترَعة.
      ---------------------------------------------------------------- */}
      {data !== null ? (
        <Card testID="operating-card" title={t.home.operating}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <StatusPill
              testID="system-state-pill"
              label={presentSystemPhase(data.system_state, data.system_state_ar).labelAr}
              tone={presentSystemPhase(data.system_state, data.system_state_ar).tone}
            />
            {data.kill_switch.active ? (
              <StatusPill testID="killswitch-pill" label="قاطع الطوارئ مُفعَّل" tone="negative" />
            ) : null}
          </View>
          <Divider />
          <Field
            testID="operating-entry"
            label={t.home.entryNew}
            value={data.locally_paused ? t.home.entryPausedLocally : t.home.entryAllowed}
            tone={data.locally_paused ? 'caution' : 'positive'}
          />
          <Field
            testID="operating-killswitch"
            label={t.system.killSwitch}
            value={data.kill_switch.active ? t.system.active : t.system.inactive}
            tone={data.kill_switch.active ? 'negative' : 'positive'}
            hint={data.kill_switch.reason_ar ?? undefined}
          />
          <Text variant="caption" tone="secondary" testID="operating-scope">
            {t.home.pauseScope}
          </Text>
        </Card>
      ) : null}

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
        <Field label="نسخة التطبيق" value={APP_VERSION} />
        <Field label="رقم البناء" value={BUILD_NUMBER} />
        <Field label="كوميت التطبيق" value={BUILD_COMMIT} />
        <Field label="زمن البناء" value={BUILD_TIME} />
        <Field
          label="بيئة التداول"
          value={TRADING_ENVIRONMENT}
          tone={TRADING_ENVIRONMENT === 'REAL' ? 'negative' : 'info'}
        />
        <Field label="كوميت الخادم" value={data?.backend_commit ?? null} />
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

          {/* ----------------------------------------------------------------
              **المزامنة والمصدر — ومعها الجملةُ التي تمنع سوء القراءة.**

              «الرصيد التجريبي ليس رأس المال» ليس زخرفاً: بدونه يُقرأ رصيدُ
              الوسيط الضخم على أنه ما تُحسب عليه الحدود، وهو ليس كذلك.
          ---------------------------------------------------------------- */}
          <Card testID="source-card" title={t.system.sourceTitle}>
            <Field
              testID="market-field"
              label={t.home.marketStatus}
              value={presentMarket(data.market.is_open).labelAr}
              hint={[data.market.reason_ar, data.market.scope_ar].filter(Boolean).join(' · ')}
            />
            {(data.market.per_instrument ?? []).map((row) => (
              <Field
                key={row.symbol}
                testID={`market-instrument-${row.symbol}`}
                label={row.symbol}
                value={row.status}
                hint={row.reason_ar}
                tone={row.tradable === false ? 'caution' : undefined}
              />
            ))}
            <Field
              testID="completeness-field"
              label={t.home.completeness}
              value={`${presentCompleteness(
                data.data_completeness.complete,
                data.data_completeness.missing.length,
              ).labelAr} · ${formatRatio(data.data_completeness.ratio)}`}
              tone={data.data_completeness.complete ? 'positive' : 'caution'}
              hint={
                [
                  data.data_completeness.missing.length > 0
                    ? data.data_completeness.missing.join('، ')
                    : null,
                  (data.data_completeness.optional_missing?.length ?? 0) > 0
                    ? `${t.home.optionalMissing}: ${(data.data_completeness.optional_missing ?? []).join('، ')}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(' · ') || undefined
              }
            />
            <Field
              testID="last-refresh-field"
              label={t.common.lastRefresh}
              value={formatSince(data.last_refresh_utc)}
              hint={formatInstant(data.last_refresh_utc)}
            />
            {r !== null ? (
              <>
                <Divider />
                <Field label="المرجعي" value={r.portfolio.baseline_equity} testID="equity-baseline" />
                <Field label="الحالي" value={r.portfolio.current_equity} testID="equity-current" />
                <Field label="لدى الوسيط" value={r.portfolio.broker_equity} testID="equity-broker" />
                {r.portfolio.diverged && r.portfolio.note_ar !== null ? (
                  <Text variant="caption" tone="secondary" testID="equity-diverged">
                    {r.portfolio.note_ar}
                  </Text>
                ) : null}
                <Banner
                  testID="demo-balance-note"
                  tone="info"
                  title={t.home.demoBalanceTitle}
                  body={`لدى الوسيط ${r.portfolio.broker_equity ?? '—'}. وكلُّ الحدود تُحسب من الحصّة المخصَّصة ${r.portfolio.baseline_equity ?? '—'} — والفرقُ يُقال ولا يُخفى.`}
                />
              </>
            ) : null}
          </Card>

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

          {/* ---- الاستراتيجية ---- */}
          {data.strategy_state !== null ? (
            <Card testID="strategy-card" title={t.home.strategy}>
              <Field label="الاستراتيجية" value={data.strategy_state.title_ar} />
              <Field
                label="الحالة"
                value={data.strategy_state.state}
                tone={data.strategy_state.live_eligible ? 'positive' : 'caution'}
                hint={
                  data.strategy_state.live_eligible
                    ? 'مُجازة للتنفيذ على الخادم.'
                    : 'غير مُجازة للتنفيذ بعد.'
                }
              />
            </Card>
          ) : null}

          {/* ---- الحدث القادم: يمنع التداول، فموضعُه حيث تُقرأ شروط التشغيل ---- */}
          <Card testID="event-card" title={t.home.upcomingEvent}>
            {data.upcoming_event !== null ? (
              <>
                <Field label="الحدث" value={data.upcoming_event.title_ar} />
                <Field
                  label="الوقت"
                  value={formatInstant(data.upcoming_event.at_utc)}
                  hint={data.upcoming_event.impact_ar}
                  tone={data.upcoming_event.blocks_trading ? 'caution' : 'primary'}
                />
              </>
            ) : (
              <Text variant="caption" tone="tertiary" testID="no-event">
                {t.home.noEvent}
              </Text>
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

      {/*
        بقيّة شاشات هذا التبويب.

        كانت هذه الشاشات مبنيّة ومسجَّلة في `_layout` ومُختبَرة — **ولا صفَّ
        انتقالٍ واحد يفتحها**. فالتبويبات الأربعة تصل إلى أربع شاشات، والباقي
        لا يُفتَح إلا برابطٍ عميق من إشعار. وهو العطل نفسه المتكرر في هذا
        المشروع بصورة أخرى: شيءٌ بُني ولم يُنفَّذ قط.

        ويحرسه الآن `__tests__/navigation-reach.test.tsx`: كل شاشة تحت
        `(app)` يجب أن يصل إليها تبويبٌ أو صفٌّ من شاشة تبويب.
      */}
      <Card testID="system-more-card" title={t.nav.more}>
        <NavRow
          testID="nav-providers"
          label={t.nav.providers}
          hint={t.navHint.providers}
          href="/(app)/providers"
        />
        <NavRow
          testID="nav-audit"
          label={t.nav.audit}
          hint={t.navHint.audit}
          href="/(app)/audit"
        />
        <NavRow
          testID="nav-notifications"
          label={t.nav.notifications}
          hint={t.navHint.notifications}
          href="/(app)/notifications"
        />
        <NavRow
          testID="nav-settings"
          label={t.nav.settings}
          hint={t.navHint.settings}
          href="/(app)/settings"
        />
        <NavRow
          testID="nav-emergency"
          label={t.nav.emergency}
          hint={t.navHint.emergency}
          href="/(app)/emergency"
        />
      </Card>

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
