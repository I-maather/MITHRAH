/**
 * الروابط العميقة.
 *
 * AUTHENTICATION FIRST, ALWAYS.
 * A deep link never renders a screen on its own. `app/_layout.tsx` captures the
 * URL, holds it in session state, and only resolves it after the local gate has
 * opened *and* the app has a valid server session. A link arriving from a
 * notification, a message or a malicious page can therefore reveal nothing.
 *
 * القائمة البيضاء صريحة: أي وجهة خارجها تُهمَل بلا أثر. لا يوجد رابط يفتح
 * إجراءً — الروابط تفتح شاشات عرض فقط، والطوارئ تُفتح كشاشة لا كفعل.
 */

export const DEEP_LINK_SCHEME = 'maather';

/** الوجهات المسموح بها. أسماؤها مسارات داخلية لا عناوين خادم. */
const ALLOWED: Record<string, string> = {
  home: '/(app)/home',
  intelligence: '/(app)/intelligence',
  decision: '/(app)/decision',
  profiles: '/(app)/profiles',
  position: '/(app)/position',
  history: '/(app)/history',
  performance: '/(app)/performance',
  providers: '/(app)/providers',
  notifications: '/(app)/notifications',
  audit: '/(app)/audit',
  system: '/(app)/system',
  settings: '/(app)/settings',
  emergency: '/(app)/emergency',
};

export interface ResolvedLink {
  /** المسار الداخلي، أو null إذا كان الرابط غير مسموح. */
  path: string | null;
  reasonAr: string;
}

/**
 * يحوّل رابطاً واردًا إلى مسار داخلي.
 *
 * لا يقبل إلا مخطط التطبيق نفسه، ولا يقبل معاملات استعلام إطلاقاً: أي معامل
 * يعني محاولة تمرير حالة من الخارج، وهذا التطبيق لا يقبل حالة من الخارج.
 */
export function resolveDeepLink(rawUrl: string): ResolvedLink {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return { path: null, reasonAr: 'رابط غير صالح — أُهمل.' };
  }

  if (url.protocol !== `${DEEP_LINK_SCHEME}:`) {
    return { path: null, reasonAr: 'رابط من خارج التطبيق — أُهمل.' };
  }

  if (url.search.length > 0) {
    return { path: null, reasonAr: 'رابط يحمل معاملات — أُهمل، فالتطبيق لا يقبل حالة خارجية.' };
  }

  // maather://decision  ⇒ host = "decision"، والمسار الفارغ.
  const target = (url.hostname.length > 0 ? url.hostname : url.pathname.replace(/^\/+/, ''))
    .replace(/\/+$/, '')
    .toLowerCase();

  const path = ALLOWED[target];
  if (path === undefined) {
    return { path: null, reasonAr: 'وجهة غير معروفة — أُهملت.' };
  }
  return { path, reasonAr: 'وجهة مسموحة.' };
}

/** أسماء الوجهات المسموح بها — يستعملها الاختبار. */
export const ALLOWED_DEEP_LINK_TARGETS: readonly string[] = Object.keys(ALLOWED);
