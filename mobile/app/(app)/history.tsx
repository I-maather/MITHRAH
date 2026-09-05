import React from 'react';
import { View } from 'react-native';

import { useEndpoint } from '@/api/useEndpoint';
import {
  Banner,
  Card,
  Divider,
  Vacancy,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  SectionTitle,
  StatusPill,
  Tag,
  Text,
  Trio,
  type TradeKind,
} from '@/components';
import { fixtures, isPreviewMode, previewOr } from '@/fixtures';
import { formatInstant, t } from '@/i18n';
import { useTheme } from '@/theme';
import { presentPnlTone } from '@/utils/present';
import { anyMissing, money, totalsByKind } from '@/utils/tradeTotals';

/**
 * سجل الصفقات.
 *
 * كل صفقة تحمل **سبب خروجها** لا نتيجتها وحدها: «ربح» بلا سبب لا تُعلّم شيئاً،
 * و«وقف» مع سببه تُعلّم.
 */
export default function HistoryScreen(): React.JSX.Element {
  const theme = useTheme();
  const preview = isPreviewMode();
  const { data, error, loading, refresh } = useEndpoint((c) => c.getTrades(), {
    previewData: previewOr(fixtures.trades),
  });

  if (loading && data === null) {
    return (
      <Screen title={t.history.title} preview={preview}>
        <LoadingState />
      </Screen>
    );
  }

  if (data === null) {
    return (
      <Screen title={t.history.title} preview={preview}>
        <ErrorState error={error} onRetry={refresh} />
      </Screen>
    );
  }

  const totals = totalsByKind(data.trades ?? []);
  const missing = anyMissing(totals);

  return (
    <Screen
      testID="history-screen"
      title={t.history.title}
      subtitle={`${data.trades.length}`}
      preview={preview}
      onRefresh={refresh}
      refreshing={loading}
    >
      {/*
        **قائمةٌ فارغة لا تُعرَض «لا صفقات» قبل أن نعرف أننا قرأنا.**

        كان الخادم يُعيد `[]` ثابتة بتعليقٍ يقول «قائمة فارغة صادقة: لم
        يُرسَل أمرٌ قط» — وصارت كاذبةً يوم أُغلقت أوّل صفقتين بمحقَّقٍ
        ‎−0.35‎ دولار. فالشاشة تسأل `sync.ok` أوّلاً.
      */}
      {!data.sync.ok || data.unavailable ? (
        <Banner
          testID="history-sync-error"
          tone="negative"
          title="تعذّرت قراءة الصفقات"
          body={`${data.sync.error_ar} — القائمة الفارغة هنا ليست «لا صفقات».`}
        />
      ) : data.sync.stale ? (
        <Banner
          testID="history-sync-stale"
          tone="caution"
          title="قراءةٌ قديمة"
          body={`آخر مزامنة قبل ${data.sync.age_seconds ?? '—'} ثانية.`}
        />
      ) : null}

      {/* ----------------------------------------------------------------
          **ثلاثة أرقامٍ بلا رابعٍ يجمعها** — بند التدقيق `E2`.

          كان هنا «المحقَّق الكلي»: رقمٌ واحد يجمع الاستراتيجي والإداري
          والتشغيلي. وجمعُها يعطي عدداً **لا يقيس أداء استراتيجية** — الإغلاقُ
          الإداري لم تتّخذه استراتيجية، وصفقةُ التشغيل غرضُها اختبار المسار
          لا الربح. ونسبةُ خسارتهما إلى استراتيجيةٍ لم تقرّرهما تُفسد كلّ
          نسبةٍ تُحسب بعدها.
      ---------------------------------------------------------------- */}
      {data.sync.ok && !data.unavailable ? (
        <>
          <Trio
            testID="history-totals"
            tiles={[
              {
                label: 'استراتيجي',
                value: money(totals.STRATEGY.value),
                tone: totals.STRATEGY.value < 0 ? 'negative' : 'positive',
              },
              {
                label: 'إداري',
                value: money(totals.ADMINISTRATIVE.value),
                tone: totals.ADMINISTRATIVE.value < 0 ? 'negative' : 'positive',
              },
              {
                label: 'تشغيلي',
                value: money(totals.COMMISSIONING.value),
                tone: totals.COMMISSIONING.value < 0 ? 'negative' : 'positive',
              },
            ]}
          />
          <Text variant="caption" tone="tertiary" testID="history-no-grand-total">
            لا يُعرض «محقَّق كلّي» في رقمٍ واحد: جمعُ الثلاثة يعطي رقماً لا يقيس
            أداء استراتيجية.
          </Text>
          {missing > 0 ? (
            <Text variant="caption" tone="caution" testID="history-partial">
              {`${missing} صفقةً لم تدخل هذه المجاميع لأنّ نتيجتها لم تُطابَق بعد — الأرقام أعلاه ناقصة، لا كاملة.`}
            </Text>
          ) : null}
          {totals.UNATTRIBUTED.counted > 0 || totals.UNATTRIBUTED.missing > 0 ? (
            <Text variant="caption" tone="caution" testID="history-unattributed">
              {`${totals.UNATTRIBUTED.counted + totals.UNATTRIBUTED.missing} صفقةً بلا نسبةٍ إلى قرار — لا تُحسب في أيٍّ من الثلاثة، ولا تُخمَّن نسبتُها.`}
            </Text>
          ) : null}
        </>
      ) : null}

      {data.sync.ok && !data.unavailable && data.trades.length > 0 ? (
        <SectionTitle
          testID="history-list-title"
          title="الصفقات المغلقة"
          note={
            data.sync.stale
              ? 'قراءةٌ قديمة'
              : `${data.trades.length} صفقة · آخر مزامنة الآن`
          }
          noteTone={data.sync.stale ? 'caution' : 'tertiary'}
        />
      ) : null}

      {!data.sync.ok || data.unavailable ? null : data.trades.length === 0 ? (
        <Vacancy
          testID="history-empty"
          what={t.history.empty}
          why={t.history.emptyWhy}
          next={t.history.emptyNext}
        />
      ) : (
        data.trades.map((trade) => (
          <Card key={trade.id ?? `${trade.instrument}-${trade.closed_utc}`} testID={`trade-${trade.id ?? 'x'}`}>
            <View
              style={{
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: theme.spacing.sm,
              }}
              accessible
              accessibilityRole="text"
              accessibilityLabel={`${trade.instrument_ar ?? trade.instrument}. ${
                trade.direction_ar
              }. ${trade.outcome_ar ?? ''}. ${trade.realised_pnl ?? ''}`}
            >
              <Text variant="bodyStrong" style={{ flex: 1 }}>
                {trade.instrument_ar ?? trade.instrument}
              </Text>
              {/* **نسبةُ الصفقة على كلّ صفّ** لا على التشغيلية وحدها:
                  الإغلاقُ الإداري كان يُقرأ صفقةَ استراتيجية. */}
              <Tag kind={(trade.kind ?? 'UNATTRIBUTED') as TradeKind} />
              {trade.outcome_ar !== null ? (
                <StatusPill
                  label={trade.outcome_ar}
                  tone={
                    trade.realised_pnl_sign === 'POSITIVE'
                      ? 'positive'
                      : trade.realised_pnl_sign === 'NEGATIVE'
                        ? 'negative'
                        : 'neutral'
                  }
                />
              ) : null}
            </View>

            <Divider />

            <Field label="الاتجاه" value={trade.direction_ar} />
            <Field label={t.history.opened} value={formatInstant(trade.opened_utc)} />
            <Field label={t.history.closed} value={formatInstant(trade.closed_utc)} />
            <Field label="سعر الدخول" value={trade.entry_price} />
            <Field label="سعر الخروج" value={trade.exit_price} />
            <Field
              label={t.history.result}
              value={trade.realised_pnl}
              tone={presentPnlTone(trade.realised_pnl_sign)}
              large
            />
            <Field label="الاستراتيجية" value={trade.strategy_ar} />
            <Field label={t.history.exitReason} value={trade.exit_reason_ar} />
          </Card>
        ))
      )}
    </Screen>
  );
}
