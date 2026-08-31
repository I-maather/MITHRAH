import type { ToneName } from '@/theme';
import type {
  FinalDecision,
  NotificationKind,
  SystemPhase,
} from '@/api/types';

/**
 * تحويل حالات الخادم إلى عرض.
 *
 * كل دالة هنا تعيد **نصاً ولوناً معاً**، فلا تُحمَّل الحالة على اللون وحده.
 * The label always carries the full meaning; the tone is redundant reinforcement.
 */

export interface Presentation {
  labelAr: string;
  tone: ToneName;
}

export function presentSystemPhase(
  phase: SystemPhase,
  overrideAr: string | null,
): Presentation {
  const base: Presentation = ((): Presentation => {
    switch (phase) {
      case 'RUNNING':
        return { labelAr: 'يعمل', tone: 'positive' };
      case 'PAUSED':
        return { labelAr: 'موقوف مؤقتاً', tone: 'caution' };
      case 'KILL_SWITCH':
        return { labelAr: 'قاطع الطوارئ مُفعَّل', tone: 'negative' };
      case 'STARTING':
        return { labelAr: 'قيد الإقلاع', tone: 'info' };
      case 'DEGRADED':
        return { labelAr: 'يعمل بنقص', tone: 'caution' };
      case 'UNKNOWN':
      default:
        return { labelAr: 'غير معروفة', tone: 'neutral' };
    }
  })();
  return overrideAr === null || overrideAr.length === 0
    ? base
    : { labelAr: overrideAr, tone: base.tone };
}

export function presentDecision(
  decision: FinalDecision,
  overrideAr: string | null,
): Presentation {
  const base: Presentation = ((): Presentation => {
    switch (decision) {
      case 'ELIGIBLE':
        // «مؤهّل» ليست دعوة للتنفيذ: الخادم وحده ينفّذ، والتطبيق يعرض.
        return { labelAr: 'مؤهّل', tone: 'positive' };
      case 'NO_TRADE':
        return { labelAr: 'امتناع', tone: 'caution' };
      case 'WAIT':
        return { labelAr: 'انتظار', tone: 'info' };
      case 'BLOCKED':
        return { labelAr: 'ممنوع', tone: 'negative' };
      case 'UNKNOWN':
      default:
        return { labelAr: 'غير معروف', tone: 'neutral' };
    }
  })();
  return overrideAr === null || overrideAr.length === 0
    ? base
    : { labelAr: overrideAr, tone: base.tone };
}

export function presentConnection(connected: boolean): Presentation {
  return connected
    ? { labelAr: 'متصل', tone: 'positive' }
    : { labelAr: 'غير متصل', tone: 'negative' };
}

export function presentMarket(isOpen: boolean): Presentation {
  return isOpen
    ? { labelAr: 'السوق مفتوح', tone: 'positive' }
    : { labelAr: 'السوق مغلق', tone: 'neutral' };
}

export function presentCompleteness(complete: boolean, missingCount: number): Presentation {
  if (complete) {
    return { labelAr: 'مكتملة', tone: 'positive' };
  }
  return {
    labelAr: missingCount > 0 ? `ناقصة (${missingCount})` : 'ناقصة',
    tone: 'caution',
  };
}

export function presentPnlTone(
  sign: 'POSITIVE' | 'NEGATIVE' | 'FLAT' | null,
): 'positive' | 'negative' | 'primary' {
  if (sign === 'POSITIVE') {
    return 'positive';
  }
  if (sign === 'NEGATIVE') {
    return 'negative';
  }
  return 'primary';
}

const NOTIFICATION_LABELS: Record<NotificationKind, { ar: string; tone: ToneName }> = {
  ELIGIBLE_SETUP_DETECTED: { ar: 'إعداد مؤهّل', tone: 'accent' },
  NO_TRADE_EVENT_RISK: { ar: 'امتناع لخطر حدث', tone: 'caution' },
  BROKER_CONFIRMATION: { ar: 'تأكيد من الوسيط', tone: 'info' },
  STOP_LOSS_EVENT: { ar: 'ضرب وقف', tone: 'negative' },
  TAKE_PROFIT_EVENT: { ar: 'بلوغ هدف', tone: 'positive' },
  SPREAD_ANOMALY: { ar: 'شذوذ في الفارق', tone: 'caution' },
  STALE_DATA: { ar: 'بيانات قديمة', tone: 'caution' },
  PROVIDER_FAILURE: { ar: 'عطل مزوّد', tone: 'negative' },
  BROKER_DISCONNECT: { ar: 'انقطاع الوسيط', tone: 'negative' },
  DAILY_LIMIT_REACHED: { ar: 'بلوغ الحد اليومي', tone: 'caution' },
  WEEKLY_LIMIT_REACHED: { ar: 'بلوغ الحد الأسبوعي', tone: 'caution' },
  TWO_LOSS_LOCK: { ar: 'قفل الخسارتين', tone: 'negative' },
  KILL_SWITCH_ACTIVATED: { ar: 'تفعيل قاطع الطوارئ', tone: 'negative' },
  DAILY_SUMMARY: { ar: 'ملخّص اليوم', tone: 'neutral' },
};

export function presentNotification(kind: NotificationKind): Presentation {
  const found = NOTIFICATION_LABELS[kind];
  return found === undefined
    ? { labelAr: 'إشعار', tone: 'neutral' }
    : { labelAr: found.ar, tone: found.tone };
}

export function presentStage(passed: boolean | null): Presentation {
  if (passed === true) {
    return { labelAr: 'اجتازت', tone: 'positive' };
  }
  if (passed === false) {
    return { labelAr: 'أخفقت', tone: 'negative' };
  }
  return { labelAr: 'لم تُقيَّم', tone: 'neutral' };
}

export function presentProvider(configured: boolean, healthy: boolean | null): Presentation {
  if (!configured) {
    return { labelAr: 'غير مُعدّ', tone: 'caution' };
  }
  if (healthy === true) {
    return { labelAr: 'سليم', tone: 'positive' };
  }
  if (healthy === false) {
    return { labelAr: 'متعطّل', tone: 'negative' };
  }
  return { labelAr: 'غير معروف', tone: 'neutral' };
}

/**
 * نصٌّ من الخادم ⇒ رقم، أو `null`.
 *
 * الأرقام تصل نصوصاً منسَّقة — بفواصل آلاف، وبعلامة موجب صريحة، وبسالبٍ
 * يونيكودي (−) لا هو ناقص ASCII. و`Number('١٫٥')` يعطي `NaN`، و`Number('')`
 * يعطي **صفراً** — وهذا أخطرهما: صفرٌ مُختلَق يُرسم على مقياس فيبدو معلومة.
 *
 * فالقاعدة هنا: ما لا يُقرأ رقماً يُعاد `null`، والمكوّن يغيب بدل أن يكذب.
 */
export function toNumber(text: string | null | undefined): number | null {
  if (text === null || text === undefined) return null;
  const cleaned = text
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[\u06f0-\u06f9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/\u066b/g, '.')          // الفاصلة العشرية العربية
    .replace(/[\u066c,\s\u066a+]/g, '')  // فاصل الآلاف والمسافات والنسبة والموجب
    .replace(/[\u2212\u2013\u2014]/g, '-');
  if (cleaned === '' || cleaned === '-') return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}
