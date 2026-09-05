import type { OpenPositionView } from './types';

/**
 * مجاميعُ المراكز — **والمجموعُ الناقص يُعلَن ناقصاً**.
 *
 * الشاشة كانت تملك المصفوفة كاملةً ولا تجمعها: لا تعرّضٌ كلّي، ولا مخاطرةٌ
 * مفتوحة، ولا كشفٌ لتكرار الأداة. ويوم 2026-09-04 كان على GBPUSD مركزان
 * في اليوم نفسه — **ضِعف المخاطرة المعتمدة على أداة واحدة** — وسطرٌ واحد
 * كان سيقول ذلك.
 *
 * والقاعدة هنا أنّ **مجموعاً يُخفي ما سقط منه أسوأ من لا مجموع**: حقلٌ
 * فارغٌ في مركزٍ يجعل المجموع أقلّ من الحقيقة، ويُقرَأ على أنه الحقيقة.
 * فيُعاد العدد المحسوب والعدد المتروك معاً، وتقرّر الشاشة كيف تقولهما.
 */

export interface Total {
  /** المجموع على ما أمكن قراءته. `null` حين لم يُقرأ شيء. */
  value: number | null;
  /** كم مركزاً دخل في المجموع. */
  counted: number;
  /** كم مركزاً سقط لغياب القيمة. */
  missing: number;
}

const parse = (raw: string | null | undefined): number | null => {
  if (raw === null || raw === undefined) {
    return null;
  }
  const cleaned = raw.replace(/,/g, '').trim();
  if (cleaned === '') {
    return null;
  }
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
};

export function sumOf(
  positions: readonly OpenPositionView[],
  field: 'notional_display' | 'risk_at_stop' | 'unrealised_pnl',
): Total {
  let total = 0;
  let counted = 0;
  let missing = 0;
  for (const position of positions) {
    const value = parse(position[field]);
    if (value === null) {
      missing += 1;
    } else {
      total += value;
      counted += 1;
    }
  }
  return { value: counted === 0 ? null : total, counted, missing };
}

export interface Duplicate {
  instrument: string;
  count: number;
}

/**
 * أدواتٌ تحمل أكثر من مركز.
 *
 * لا يُقارَن الاتجاه: مركزان متعاكسان على الأداة نفسها ليسا تحوّطاً هنا،
 * هما تعرّضان ورسمان وسبريدان — والتنبيه يقول «تكرار» ويترك الحكم.
 */
export function duplicateInstruments(
  positions: readonly OpenPositionView[],
): Duplicate[] {
  const counts = new Map<string, number>();
  for (const position of positions) {
    const key = (position.instrument ?? '').trim().toUpperCase();
    if (key === '') {
      continue;
    }
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([instrument, count]) => ({ instrument, count }))
    .sort((a, b) => b.count - a.count || a.instrument.localeCompare(b.instrument));
}
