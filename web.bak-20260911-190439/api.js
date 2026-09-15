/* ─────────────────────────────────────────────────────────────
   مِثْراة — طبقةُ الاتصال

   · العنوانُ يُشتقّ من الصفحة نفسها، لا يُخبَز في البناء. هذا هو
     العطبُ الذي أوقف نسخةَ الجوال: عنوانٌ مثبَّتٌ وقتَ البناء مات
     حين تغيّرت الشبكة. الصفحةُ المخدومة من الخادم تعرف خادمَها
     دائماً لأنها قادمةٌ منه.
   · الرمزُ في localStorage للمتصفّح وحده، ولا يُطبع ولا يُسجَّل.
   ───────────────────────────────────────────────────────────── */

const BASE = `${location.origin}/api/mobile`;
const TOKEN_KEY = "mathrah.session";

export const token = {
  get:   () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set:   (v) => { try { localStorage.setItem(TOKEN_KEY, v); } catch {} },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch {} },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function call(path, { method = "GET", body = null, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body) headers["Content-Type"] = "application/json";
  const t = auth ? token.get() : null;
  if (t) headers.Authorization = `Bearer ${t}`;

  const ctrl = new AbortController();
  const bail = setTimeout(() => ctrl.abort(), 20000);
  let res;
  try {
    res = await fetch(`${BASE}/${path}`, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
      cache: "no-store",
    });
  } finally {
    clearTimeout(bail);
  }

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  describe:     () => call("v1/describe", { auth: false }),
  status:       () => call("v1/status"),
  risk:         () => call("v1/risk"),
  positions:    () => call("v1/positions/current"),
  trades:       () => call("v1/trades"),
  performance:  () => call("v1/performance"),
  decision:     () => call("v1/decision/latest"),
  intelligence: () => call("v1/intelligence/latest"),
  participation:() => call("v1/participation/today"),
  candles:      () => call("v1/market/candles"),
  audit:        () => call("v1/audit/recent"),
  scan:         () => call("v1/scan/latest"),
  providers:    () => call("v1/providers/health"),

  /* المسارُ الوحيدُ الذي يُنشئ جلسةً. عقدُه يُقرأ من الخادم لا يُخمَّن:
     إن رُفض بـ422 عرضنا ما طلبه الخادم بدل أن نخترع حقلاً. */
  enroll: (payload) => call("session/enroll", { method: "POST", body: payload, auth: false }),

  /* مسارٌ يقلّل المخاطرة فقط. لا مسارَ يفتح تداولاً من هنا. */
  pause:      (reason) => call("v1/pause/request", { method: "POST", body: { reason } }),
  killswitch: (confirm) => call("v1/killswitch/activate", { method: "POST", body: { confirmation: confirm } }),
};

/* ── الاستطلاعُ الدوري ──────────────────────────────────────
   يتوقّف حين تختفي الصفحة ويستأنف فوراً عند العودة — لأن التحديثَ
   في الخلفية إنفاقُ بطاريةٍ بلا قارئ، ولأن العودةَ إلى شاشةٍ قديمة
   هي الشكوى نفسها التي سمعتُها: «متصل بس واقف على قيم قديمة». */
export function poll(fn, ms = 20000) {
  let timer = null, stopped = false;

  const tick = async () => {
    if (stopped || document.hidden) return;
    try { await fn(); } catch (e) { /* الخطأُ يُعرض في الواجهة لا في الحلقة */ }
  };

  const start = () => {
    clearInterval(timer);
    timer = setInterval(tick, ms);
    tick();
  };

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearInterval(timer);
    else start();
  });

  start();
  return () => { stopped = true; clearInterval(timer); };
}
