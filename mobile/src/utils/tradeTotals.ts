import type { TradeKind } from '@/components/Tag';

/**
 * المحقَّق **مصنَّفاً**، لا رقماً واحداً.
 *
 * بند التدقيق `E2` بنصّه: جمعُ الاستراتيجي والإداري والتشغيلي في رقمٍ واحد
 * يعطي عدداً **لا يقيس أداء استراتيجية**. الإغلاقُ الإداري لم تتّخذه
 * استراتيجية، وصفقةُ التشغيل غرضُها اختبار المسار لا الربح — ونسبةُ خسارتهما
 * إلى استراتيجيةٍ لم تقرّرهما تُفسد كلّ نسبةٍ تُحسب بعدها.
 *
 * ## والمجموع الجزئيّ يُعلَن جزئياً
 *
 * صفقةٌ بلا نتيجةٍ معروفة لا تُجمع صفراً: تُعَدّ في `missing`، ويُقال للقارئ
 * إنّ الرقم أمامه ناقص. وهذا هو الفرق بين «المحقَّق ‎−0.79‎» و«المحقَّق
 * ‎−0.79‎ من صفقتين، وثالثةٌ لا تُعرف نتيجتها».
 */

export interface KindTotal {
  /** المجموع على ما عُرف وحده. */
  value: number;
  /** كم صفقةً دخلت المجموع. */
  counted: number;
  /** كم صفقةً لم تدخله لأن نتيجتها مجهولة. */
  missing: number;
}

export type TradeTotals = Record<TradeKind, KindTotal>;

const EMPTY = (): KindTotal => ({ value: 0, counted: 0, missing: 0 });

/**
 * يقرأ رقماً من نصّ الخادم — أو `null` إن لم يكن رقماً.
 *
 * الخادم يرسل الأرقام نصوصاً كي لا تفقد دقّتها في JSON. والسالبُ قد يأتي
 * بالشرطة العربية `−` لا بالناقص اللاتيني، وهما محرفان مختلفان — وخلطُهما
 * يجعل خسارةً تُقرأ `NaN` فتُطرح من العدّ صامتة.
 */
export const parseMoney = (raw: string | null | undefined): number | null => {
  if (raw === null || raw === undefined) return null;
  const cleaned = raw.replace(/[,\s+]/g, '').replace(/[−–—]/g, '-');
  if (cleaned === '' || cleaned === '-') return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
};

export interface TradeLike {
  kind?: string | null;
  realised_pnl?: string | null;
}

const KINDS: TradeKind[] = [
  'STRATEGY',
  'ADMINISTRATIVE',
  'COMMISSIONING',
  'UNATTRIBUTED',
];

const kindOf = (raw: string | null | undefined): TradeKind =>
  KINDS.includes(raw as TradeKind) ? (raw as TradeKind) : 'UNATTRIBUTED';

export function totalsByKind(trades: readonly TradeLike[]): TradeTotals {
  const out = {
    STRATEGY: EMPTY(),
    ADMINISTRATIVE: EMPTY(),
    COMMISSIONING: EMPTY(),
    UNATTRIBUTED: EMPTY(),
  } as TradeTotals;

  for (const trade of trades) {
    const bucket = out[kindOf(trade.kind)];
    const value = parseMoney(trade.realised_pnl);
    if (value === null) {
      bucket.missing += 1;
      continue;
    }
    bucket.value += value;
    bucket.counted += 1;
  }
  return out;
}

/** نصُّ المبلغ بإشارته — والصفر بلا إشارة. */
export const money = (value: number): string =>
  value === 0 ? '0.00' : `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}`;

/** هل في المجموع نقص؟ يُقال ولا يُبتلع. */
export const anyMissing = (totals: TradeTotals): number =>
  KINDS.reduce((sum, kind) => sum + totals[kind].missing, 0);
