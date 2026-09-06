import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '@/auth/SessionProvider';
import { observeEnvironment } from './environment';
import type { MobileApiClient } from './client';
import type { MobileEnvelope } from './types';

/**
 * عمر الحالة قبل أن تُوصَف بأنها **قديمة**.
 * A screen older than this shows a stale banner. The number is small on purpose:
 * a two-minute-old risk figure looks current but may not be.
 */
export const STALE_AFTER_MS = 90_000;

export interface EndpointState<T> {
  data: T | null;
  envelope: MobileEnvelope<T> | null;
  error: unknown;
  loading: boolean;
  /** true حين تجاوز عمر آخر نجاح `STALE_AFTER_MS`. */
  stale: boolean;
  /** لحظة آخر نجاح (مللي ثانية محلية) — أو null. */
  fetchedAt: number | null;
  refresh: () => void;
}

/**
 * جلب مسار واحد.
 *
 * السلوك المقصود عند الفشل: **الاحتفاظ بآخر بيانات ناجحة** مع رفع علم القِدَم،
 * لا محوها. شاشة فارغة تدفع المالكة إلى إعادة الفتح مراراً؛ شاشة قديمة موسومة
 * بأنها قديمة تقول الحقيقة.
 */
export function useEndpoint<T>(
  select: (client: MobileApiClient) => Promise<MobileEnvelope<T>>,
  options?: { previewData?: T | null; enabled?: boolean },
): EndpointState<T> {
  const { client, status } = useSession();
  const enabled = (options?.enabled ?? true) && status === 'UNLOCKED';
  const preview = options?.previewData ?? null;

  const [data, setData] = useState<T | null>(preview);
  const [envelope, setEnvelope] = useState<MobileEnvelope<T> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(preview === null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(preview === null ? null : Date.now());
  const [tick, setTick] = useState(0);

  const selectRef = useRef(select);
  selectRef.current = select;

  useEffect(() => {
    if (preview !== null) {
      // وضع المعاينة: لا طلب شبكة إطلاقاً.
      setLoading(false);
      return;
    }
    if (!enabled) {
      return;
    }
    let alive = true;
    setLoading(true);
    void (async () => {
      try {
        const result = await selectRef.current(client);
        if (!alive) {
          return;
        }
        setEnvelope(result);
        setData(result.data);
        // أيّ حمولةٍ تحمل حالة الوسيط تُحدِّث شارة البيئة في كل الشاشات.
        observeEnvironment(result.data);
        setError(null);
        setFetchedAt(Date.now());
      } catch (caught) {
        if (!alive) {
          return;
        }
        // البيانات السابقة تبقى معروضة، ويُرفع علم الخطأ فوقها.
        setError(caught);
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [client, enabled, preview, tick]);

  // مؤقّت خفيف كي ينتقل العرض إلى «قديم» دون تفاعل من المستخدمة.
  const [, setStaleTick] = useState(0);
  useEffect(() => {
    if (fetchedAt === null) {
      return;
    }
    const timer = setInterval(() => {
      setStaleTick((n) => n + 1);
    }, 20_000);
    return () => {
      clearInterval(timer);
    };
  }, [fetchedAt]);

  /**
   * **الاستطلاع التلقائي.**
   *
   * كانت الشاشة تُحضِر البيانات **مرّةً واحدة** ثم لا تسأل بعدها أبداً؛
   * و`refresh` بيدِ المستخدمة وحدها. فبدت الشاشة صورةً لا نظاماً يعمل:
   * السعر لا يتحرّك، والقرارُ لا يتبدّل، ودورةُ الستّين ثانية تجري على
   * الخادم ولا يصل منها شيء.
   *
   * وليس هذا «مباشراً»: دورةُ القرار ستّون ثانية، فالسؤالُ كلَّ عشرين
   * ثانيةً يضمن ألّا يمضي على الشاشة أكثرُ من دورةٍ واحدة. والشارةُ تبقى
   * تقول متى وصلت الحمولة، فلا تدّعي الشاشةُ حداثةً ليست لها.
   *
   * والمعاينةُ لا تُستطلَع: بياناتُها ثابتةٌ في الملف، وسؤالُها عبث.
   */
  useEffect(() => {
    if (!enabled || preview) {
      return;
    }
    const timer = setInterval(() => {
      setTick((n) => n + 1);
    }, 20_000);
    return () => {
      clearInterval(timer);
    };
  }, [enabled, preview]);

  const refresh = useCallback(() => {
    setTick((n) => n + 1);
  }, []);

  const stale = fetchedAt !== null && Date.now() - fetchedAt > STALE_AFTER_MS;

  return { data, envelope, error, loading, stale, fetchedAt, refresh };
}
