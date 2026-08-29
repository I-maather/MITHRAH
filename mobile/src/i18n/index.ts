export { t, type Strings } from './ar';
export { LOCALE, applyRtl, rtlState, textEnd, textStart, type RtlState } from './rtl';

/**
 * تنسيق وقت UTC للعرض بتوقيت الجهاز.
 * الخادم يرسل ISO-8601 بتوقيت UTC؛ العرض محلي، والقيمة الأصلية لا تُغيَّر.
 */
export function formatInstant(iso: string | null): string {
  if (iso === null || iso.length === 0) {
    return '—';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

/** «منذ ٣ دقائق» — للمدد القصيرة فقط، وإلا يُعرض التاريخ. */
export function formatSince(iso: string | null, now: number = Date.now()): string {
  if (iso === null || iso.length === 0) {
    return '—';
  }
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return '—';
  }
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 45) {
    return 'الآن';
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `منذ ${minutes} دقيقة`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `منذ ${hours} ساعة`;
  }
  return formatInstant(iso);
}

/** يُعيد مدّة التبريد بصيغة مقروءة. */
export function formatCooling(seconds: number | null): string {
  if (seconds === null || seconds <= 0) {
    return '—';
  }
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours} ساعة و${minutes} دقيقة`;
  }
  return `${minutes} دقيقة`;
}

/** نسبة مئوية من كسر 0..1، أو «—» إذا لم تُحتسب. */
export function formatRatio(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) {
    return '—';
  }
  return `${Math.round(ratio * 100)}٪`;
}
