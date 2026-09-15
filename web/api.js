/* ─────────────────────────────────────────────────────────────
   مِثْراة — طبقةُ الاتصال

   مكتوبةٌ على **عقد الخادم الفعلي** بعد قراءته، لا على تخمين:
   `backend/app/mobile/routes.py` و`mobile/src/api/types.ts`.

   · العنوانُ يُشتقّ من الصفحة نفسها. هذا هو العطب الذي قتل نسخةَ الجوال:
     عنوانٌ مخبوزٌ وقتَ البناء مات حين تغيّرت الشبكة. والصفحةُ المخدومة
     من الخادم تعرف خادمَها دائماً لأنها قادمةٌ منه.
   · كلُّ استجابةِ GET مغلَّفةٌ بـ`{route, server_time_utc, device_id,
     authorises_execution, data}` — ونحن **نتحقّق** من الغلاف لا نكتفي
     بفضّه: استجابةٌ تدّعي `authorises_execution: true` تُرفَض.
   · الرمزان في localStorage لهذا المتصفّح وحده، ولا يُطبعان ولا يُسجَّلان.
   ───────────────────────────────────────────────────────────── */

const ORIGIN   = location.origin;
const V1       = `${ORIGIN}/api/mobile/v1`;
const ENROLL   = `${ORIGIN}/api/mobile/session/enroll`;
const REFRESH  = `${ORIGIN}/api/mobile/session/refresh`;

const K_ACCESS   = "mathrah.access";
const K_REFRESH  = "mathrah.refresh";
const K_IDENTITY = "mathrah.identity";

const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  del: (k) => { try { localStorage.removeItem(k); } catch {} },
};

export const session = {
  access:  () => ls.get(K_ACCESS),
  refresh: () => ls.get(K_REFRESH),
  hasSession: () => Boolean(ls.get(K_ACCESS) && ls.get(K_REFRESH)),
  save: (access, refresh) => { ls.set(K_ACCESS, access); ls.set(K_REFRESH, refresh); },
  clear: () => { ls.del(K_ACCESS); ls.del(K_REFRESH); },

  /** هويةُ الجهاز: معرّفٌ عشوائيٌّ يُولَّد مرّةً ويُحفَظ. ليس مفتاحاً ولا
      تقوم عليه مصادقة — المصادقةُ كلُّها برموز الخادم قصيرة العمر. */
  identity() {
    let v = ls.get(K_IDENTITY);
    if (!v) {
      const b = new Uint8Array(16);
      crypto.getRandomValues(b);
      v = "web-" + [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      ls.set(K_IDENTITY, v);
    }
    return v;
  },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
    this.messageAr = (body && (body.error_ar || body.detail_ar)) || null;
  }
}

async function raw(url, { method = "GET", body = null, token = null } = {}) {
  const headers = { accept: "application/json" };
  if (body) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;

  const ctrl = new AbortController();
  const bail = setTimeout(() => ctrl.abort(), 20000);
  let res;
  try {
    res = await fetch(url, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
      cache: "no-store",
    });
  } finally { clearTimeout(bail); }

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

/* ── التجديد ────────────────────────────────────────────────
   الرمزُ يُدوَّر إجبارياً: المُقدَّم يُبطَل ويُصدر زوجٌ جديد. فطلبان
   متزامنان بالرمز نفسه يُبطل أحدُهما الآخر — ولهذا يُشترك الطلبُ
   الواحد بين كلِّ من ينتظره. */
let refreshing = null;

async function renew() {
  if (refreshing) return refreshing;
  const rt = session.refresh();
  if (!rt) throw new ApiError(401, { error_ar: "لا جلسة." });
  refreshing = raw(REFRESH, { method: "POST", body: { refresh_token: rt } })
    .then((d) => {
      const a = d && (d.access_token || (d.data && d.data.access_token));
      const r = d && (d.refresh_token || (d.data && d.data.refresh_token));
      if (!a || !r) throw new ApiError(500, { error_ar: "ردُّ التجديد بلا رموز." });
      session.save(a, r);
      return a;
    })
    .finally(() => { refreshing = null; });
  return refreshing;
}

/** GET على مجال البيانات، مع تجديدٍ واحدٍ عند 401 ثم استسلام. */
async function get(route) {
  let token = session.access();
  if (!token) throw new ApiError(401, { error_ar: "لا جلسة." });
  let env;
  try {
    env = await raw(`${V1}/${route}`, { token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    token = await renew();
    env = await raw(`${V1}/${route}`, { token });
  }
  return unwrap(env, route);
}

/**
 * يفضّ الغلافَ **بعد التحقّق منه**.
 *
 * `authorises_execution` ثابتٌ `false` في العقد. واستجابةٌ تقول غير ذلك
 * إمّا من خادمٍ ليس خادمَنا وإمّا من نسخةٍ كُسر عقدُها — وكلاهما سببٌ
 * للرفض لا للعرض.
 */
function unwrap(env, route) {
  if (!env || typeof env !== "object") {
    throw new ApiError(502, { error_ar: `استجابةٌ غير مفهومة من ${route}.` });
  }
  if (env.authorises_execution === true) {
    throw new ApiError(502, { error_ar: "استجابةٌ تدّعي صلاحيةَ تنفيذ — رُفضت." });
  }
  if (!("data" in env)) {
    throw new ApiError(502, { error_ar: `استجابةُ ${route} بلا حقل data.` });
  }
  return { data: env.data, at: env.server_time_utc || null };
}

export const api = {
  status:        () => get("status"),
  risk:          () => get("risk"),
  positions:     () => get("positions/current"),
  trades:        () => get("trades"),
  performance:   () => get("performance"),
  participation: () => get("participation/today"),
  candles:       () => get("market/candles"),
  audit:         () => get("audit/recent"),
};

/* ── الاقتران ───────────────────────────────────────────────
   حمولةُ الاقتران `{v,b,c,e}` تُولَّد على الخادم بأمرٍ في صدفة، عمرُها
   دقيقتان وتُستهلَك مرّة. ولا سرَّ فيها. */

export const PAYLOAD_VERSION = 1;

export function parsePairing(rawText, now = Date.now()) {
  let p;
  try { p = JSON.parse(String(rawText).trim()); }
  catch { return { ok: false, ar: "هذا ليس رمزَ اقتران مِثْراة." }; }

  if (!p || typeof p !== "object") return { ok: false, ar: "هذا ليس رمزَ اقتران مِثْراة." };

  // **لا حقل زائد.** الحقلُ الإضافي هو المكان الذي يُهرَّب فيه محتوى،
  // فيُرفَض بوجوده لا باعترافه — نفسُ حارس التطبيق والخادم.
  const extra = Object.keys(p).filter((k) => !["v", "b", "c", "e"].includes(k));
  if (extra.length) return { ok: false, ar: "رمزُ اقتران يحمل حقولاً غير متوقَّعة — رُفض." };

  if (p.v !== PAYLOAD_VERSION) return { ok: false, ar: "إصدارُ رمز الاقتران غير مدعوم." };
  if (typeof p.b !== "string" || typeof p.c !== "string" || !p.c || typeof p.e !== "number") {
    return { ok: false, ar: "رمزُ اقتران ناقصٌ أو تالف." };
  }

  const norm = (u) => String(u).replace(/\/+$/, "");
  if (norm(p.b) !== norm(ORIGIN)) {
    // الحارسُ الأهمّ: رمزٌ يشير إلى خادمٍ آخر غير الخادم الذي جاءت منه
    // هذه الصفحة غيرُ شرعيٍّ بالتعريف.
    return { ok: false, ar: `هذا الرمز يشير إلى خادمٍ آخر (${norm(p.b)}) — لن يُسجَّل الجهاز.` };
  }

  if (p.e * 1000 <= now) {
    return { ok: false, ar: "انتهت صلاحيةُ الرمز. ولّدي رمزاً جديداً من الخادم." };
  }
  return { ok: true, payload: p };
}

export async function enrol(rawText, deviceName = "متصفّح مِثْراة") {
  const checked = parsePairing(rawText);
  if (!checked.ok) return { ok: false, ar: checked.ar };

  let d;
  try {
    d = await raw(ENROLL, {
      method: "POST",
      body: {
        challenge_id: checked.payload.c,
        public_identity: session.identity(),
        device_name: deviceName,
      },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) return { ok: false, ar: "الخادمُ لا يعرف مسارَ التسجيل — يعمل بنسخةٍ أقدم." };
      if (e.status === 503) return { ok: false, ar: "طبقةُ الجوال غير مُهيّأةٍ على الخادم." };
      return { ok: false, ar: e.messageAr || "تعذّر الاقتران." };
    }
    return { ok: false, ar: "تعذّر الوصولُ إلى الخادم." };
  }

  if (d.authorises_execution === true) {
    return { ok: false, ar: "ردُّ التسجيل يدّعي صلاحيةَ تنفيذ — رُفض." };
  }
  if (!d.access_token || !d.refresh_token) {
    return { ok: false, ar: "ردُّ التسجيل بلا رموزِ جلسة." };
  }
  session.save(d.access_token, d.refresh_token);
  return { ok: true, device: d.device || null };
}

/* ── الاستطلاعُ الدوري ──────────────────────────────────────
   يتوقّف حين تختفي الصفحة ويستأنف فوراً عند العودة: التحديثُ في الخلفية
   إنفاقُ بطاريةٍ بلا قارئ، والعودةُ إلى شاشةٍ قديمة هي الشكوى نفسها التي
   سُمعت من قبل — «متصل بس واقف على قيم قديمة». */
export function poll(fn, ms = 20000) {
  let timer = null, stopped = false;

  const tick = () => {
    if (stopped || document.hidden) return;
    Promise.resolve(fn()).catch(() => {});   // الخطأُ يُعرض في الواجهة لا في الحلقة
  };
  const start = () => { clearInterval(timer); timer = setInterval(tick, ms); tick(); };

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearInterval(timer); else start();
  });

  start();
  return () => { stopped = true; clearInterval(timer); };
}
