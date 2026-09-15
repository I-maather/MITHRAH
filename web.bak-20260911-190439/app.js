/* ─────────────────────────────────────────────────────────────
   مِثْراة — الواجهة

   قاعدةٌ واحدةٌ تحكم كلَّ ما يلي: **لا تخترع قيمة.** الحقلُ الغائب
   يُعرض شَرطةً، لا صفراً ولا تقديراً. الصفرُ رقمٌ وله معنى؛ والشَرطةُ
   تقول «لم أقرأ» — وهذا هو الفرقُ الذي أعاب `why_no_trade.sh` حين
   عرض ردَّ 401 على أنه «السوقُ مغلق».
   ───────────────────────────────────────────────────────────── */

import { api, token, poll, ApiError } from "/api.js";
import { drawCandles } from "/chart.js";

const $  = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

/* ── أدواتُ القراءة الدفاعية ─────────────────────────────── */

/** يأخذ أوّلَ مفتاحٍ موجود؛ وإن لم يوجد أيٌّ منها أعاد undefined لا صفراً. */
const pick = (obj, ...keys) => {
  for (const k of keys) {
    let cur = obj;
    for (const part of k.split(".")) {
      if (cur == null) { cur = undefined; break; }
      cur = cur[part];
    }
    if (cur !== undefined && cur !== null) return cur;
  }
  return undefined;
};

const nOr = (v) => { const n = Number(v); return Number.isFinite(n) ? n : undefined; };
const dash = (v) => (v === undefined || v === null || v === "" ? "—" : v);

const money = (v) => {
  const n = nOr(v);
  if (n === undefined) return "—";
  const s = n.toFixed(2);
  return n > 0 ? `+${s}` : s;
};

const clearSkeleton = (root) => $$(".skeleton", root).forEach((e) => e.classList.remove("skeleton"));

/* ── الحالة ──────────────────────────────────────────────── */

const S = {
  symbol: null,
  candles: null,
  live: {},
  lastOk: null,
};

/* ── الاتصال ─────────────────────────────────────────────── */

function setConn(state, text) {
  const c = $("#conn");
  c.className = `chip ${state}`;
  $("#conn-t").textContent = text;
}

/* ── العرض ───────────────────────────────────────────────── */

function renderStatus(d) {
  if (!d) return;
  const env = pick(d, "environment", "broker.environment", "broker_environment", "mode");
  const mode = pick(d, "mode", "operating_mode", "risk_mode");
  $("#env").textContent = [env, mode].filter(Boolean).join(" · ") || "—";

  const box = $("#verdict");
  const line = pick(d, "verdict_ar", "headline_ar", "summary_ar", "verdict", "headline");
  const why  = pick(d, "reason_ar", "detail_ar", "note_ar", "reason");
  box.querySelector(".line").textContent = dash(line);
  box.querySelector(".why").textContent  = dash(why);

  const state = String(pick(d, "state", "status", "trading_state") || "").toUpperCase();
  let old = box.querySelector(".pill");
  if (old) old.remove();
  if (state) {
    const pill = document.createElement("span");
    const cls = /KILL|LOCK|HALT|PAUSE|STOP/.test(state) ? "stop"
              : /TRAD|ACTIVE|RUNNING|READY/.test(state) ? "ok" : "hold";
    pill.className = `pill ${cls}`;
    pill.textContent = pick(d, "state_ar", "status_ar") || state;
    box.appendChild(pill);
  }
  clearSkeleton(box);
}

function renderFigures(perf, pos) {
  const g = $("#figures");
  const realised = pick(perf || {}, "realised_total", "realized_total", "total_realised_pnl", "pnl_realised", "realised");
  const open = Array.isArray(pos) ? pos.length : pick(pos || {}, "open_count", "count");
  const wl = (() => {
    const w = nOr(pick(perf || {}, "wins", "win_count"));
    const l = nOr(pick(perf || {}, "losses", "loss_count"));
    return (w === undefined && l === undefined) ? undefined : `${w ?? "—"} / ${l ?? "—"}`;
  })();

  const cells = g.querySelectorAll(".fig .v");
  const r = nOr(realised);
  cells[0].textContent = money(realised);
  cells[0].className = `v num ${r === undefined ? "" : r > 0 ? "pos" : r < 0 ? "neg" : ""}`;
  cells[1].textContent = dash(open);
  cells[2].textContent = dash(wl);
  clearSkeleton(g);
}

function renderPositions(list) {
  const box = $("#positions");
  const rows = Array.isArray(list) ? list : pick(list || {}, "positions", "items", "open") || [];
  if (!rows.length) {
    box.innerHTML = `<div class="empty">لا مراكزَ مفتوحة الآن</div>`;
    return;
  }
  box.innerHTML = rows.map((p) => {
    const sym  = dash(pick(p, "symbol", "instrument", "epic"));
    const side = String(pick(p, "side", "direction") || "").toUpperCase();
    const size = dash(pick(p, "size", "quantity", "qty"));
    const entry = pick(p, "entry_price", "open_price", "price");
    const pnl  = nOr(pick(p, "unrealised_pnl", "unrealized_pnl", "pnl", "open_pnl"));
    const sideCls = /BUY|LONG/.test(side) ? "buy" : "sell";
    const sideAr  = /BUY|LONG/.test(side) ? "شراء" : "بيع";
    return `<div class="pos-row">
      <span class="side ${sideCls}">${sideAr}</span>
      <span>
        <span class="sym">${sym}</span>
        <span class="meta num"> · ${size} @ ${dash(entry)}</span>
      </span>
      <span class="pnl num ${pnl === undefined ? "" : pnl > 0 ? "v pos" : pnl < 0 ? "v neg" : ""}">${money(pnl)}</span>
    </div>`;
  }).join("");
}

function renderCandles(data) {
  if (!data) return;
  S.candles = data;
  const series = pick(data, "series", "candles", "bars", "by_symbol") || data;
  const symbols = Object.keys(series).filter((k) => Array.isArray(series[k]) || (series[k] && Array.isArray(series[k].bars)));
  if (!symbols.length) return;

  if (!S.symbol || !symbols.includes(S.symbol)) S.symbol = symbols[0];

  const tabs = $("#symtabs");
  if (tabs.childElementCount !== symbols.length) {
    tabs.innerHTML = symbols.map((s) => `<button data-s="${s}" aria-pressed="${s === S.symbol}">${s}</button>`).join("");
    tabs.onclick = (e) => {
      const b = e.target.closest("button"); if (!b) return;
      S.symbol = b.dataset.s;
      $$("#symtabs button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.s === S.symbol)));
      paintChart();
    };
  }
  S.live = pick(data, "live") || {};
  paintChart();
}

function paintChart() {
  const data = S.candles; if (!data || !S.symbol) return;
  const series = pick(data, "series", "candles", "bars", "by_symbol") || data;
  const raw = Array.isArray(series[S.symbol]) ? series[S.symbol] : series[S.symbol]?.bars || [];
  const bars = raw.map((b) => ({
    o: Number(pick(b, "o", "open")), h: Number(pick(b, "h", "high")),
    l: Number(pick(b, "l", "low")),  c: Number(pick(b, "c", "close")),
    t: pick(b, "t", "at_utc", "time", "timestamp"),
  })).filter((b) => Number.isFinite(b.o) && Number.isFinite(b.c));

  const live = nOr(pick(S.live, `${S.symbol}.price`));
  const last = bars.length ? bars[bars.length - 1].c : undefined;
  const shown = live ?? last;
  /* عددُ الخانات يُؤخذ من السعر نفسه لا من قاعدةٍ عامّة: الذهبُ خانتان
     والفوركس خمس، وقاعدةٌ واحدةٌ تخون إحداهما. */
  const src = pick(S.live, `${S.symbol}.price`) ?? (bars.length ? String(bars[bars.length - 1].c) : "");
  const dec = String(src).includes(".") ? String(src).split(".")[1].length : 2;
  const digits = Math.max(2, Math.min(5, dec));

  $("#px").textContent = shown === undefined ? "—" : Number(shown).toFixed(digits);

  const first = bars.length ? bars[Math.max(0, bars.length - 60)].o : undefined;
  const dEl = $("#dx");
  if (first !== undefined && shown !== undefined) {
    const pct = ((shown - first) / first) * 100;
    dEl.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
    dEl.style.color = pct >= 0 ? "var(--pos)" : "var(--neg)";
  } else { dEl.textContent = ""; }

  const levels = [];
  drawCandles($("#chart"), bars, { levels, live, digits });
}

function renderRisk(d) {
  const box = $("#riskbox");
  if (!d) { box.innerHTML = `<h2>سياسةُ المخاطرة</h2><div class="empty">تعذّرت القراءة</div>`; return; }
  const rows = [
    ["رأسُ المال المرجعي", pick(d, "reference_capital", "allocated_capital", "capital_usd")],
    ["المخاطرةُ المستهدفة", pick(d, "target_risk", "target_risk_usd", "per_trade_target")],
    ["الحدُّ الصلب للصفقة", pick(d, "hard_max_risk", "max_risk_usd", "per_trade_hard_max")],
    ["الحدُّ اليومي", pick(d, "daily_loss_limit", "daily_max_loss")],
    ["الحدُّ الأسبوعي", pick(d, "weekly_loss_limit", "weekly_max_loss")],
    ["أقصى مراكز مفتوحة", pick(d, "max_open_positions")],
    ["أوامرُ الدخول يومياً", pick(d, "max_entry_orders_per_day")],
  ];
  box.innerHTML = `<h2>سياسةُ المخاطرة</h2>` + rows.map(([k, v]) =>
    `<div class="pos-row" style="grid-template-columns:1fr auto;padding-inline:0">
       <span style="font-size:13.5px;color:var(--ink-2)">${k}</span>
       <span class="num" style="font-weight:600">${dash(v)}</span>
     </div>`).join("");
}

function renderFunnel(d) {
  const box = $("#funnel");
  if (!d) { box.innerHTML = `<h2>مسارُ الفرص · ٢٤ ساعة</h2><div class="empty">تعذّرت القراءة</div>`; return; }
  const steps = [
    ["مسحٌ", pick(d, "scanned", "scan_count")],
    ["مؤهَّل", pick(d, "eligible", "eligible_count")],
    ["إشارة", pick(d, "signals", "signal_count")],
    ["أجازتها المخاطرة", pick(d, "risk_approved", "approved_count")],
    ["أُرسلت", pick(d, "submitted", "submitted_count")],
    ["نُفّذت", pick(d, "filled", "filled_count")],
  ];
  box.innerHTML = `<h2>مسارُ الفرص · ٢٤ ساعة</h2>` + steps.map(([k, v]) =>
    `<div class="pos-row" style="grid-template-columns:1fr auto;padding-inline:0">
       <span style="font-size:13.5px;color:var(--ink-2)">${k}</span>
       <span class="num" style="font-weight:600">${dash(v)}</span>
     </div>`).join("");
}

function renderList(sel, rows, fmt, emptyText) {
  const box = $(sel);
  const list = Array.isArray(rows) ? rows : pick(rows || {}, "items", "entries", "trades", "events") || [];
  if (!list.length) { box.innerHTML = `<div class="empty">${emptyText}</div>`; return; }
  box.innerHTML = list.slice(0, 60).map(fmt).join("");
}

/* ── الدورة ──────────────────────────────────────────────── */

async function refresh() {
  const settled = await Promise.allSettled([
    api.status(), api.positions(), api.performance(), api.candles(),
  ]);
  const [st, ps, pf, cd] = settled;

  const unauth = settled.some((r) => r.status === "rejected" && r.reason instanceof ApiError && r.reason.status === 401);
  if (unauth) { token.clear(); showGate("انتهت صلاحيةُ الاقتران — أعيدي الإدخال"); return; }

  const anyOk = settled.some((r) => r.status === "fulfilled");
  if (!anyOk) { setConn("down", "لا اتصال"); return; }

  S.lastOk = new Date();
  setConn("live", "حيّ");

  if (st.status === "fulfilled") renderStatus(st.value);
  if (ps.status === "fulfilled") renderPositions(ps.value);
  renderFigures(pf.status === "fulfilled" ? pf.value : null, ps.status === "fulfilled" ? ps.value : null);
  if (cd.status === "fulfilled") renderCandles(cd.value);
}

async function refreshSecondary() {
  const [rk, pt, tr, au] = await Promise.allSettled([
    api.risk(), api.participation(), api.trades(), api.audit(),
  ]);
  renderRisk(rk.status === "fulfilled" ? rk.value : null);
  renderFunnel(pt.status === "fulfilled" ? pt.value : null);

  if (tr.status === "fulfilled") {
    renderList("#trades", tr.value, (t) => {
      const pnl = nOr(pick(t, "realised_pnl", "realized_pnl", "pnl"));
      return `<div class="pos-row">
        <span class="side ${/BUY|LONG/i.test(pick(t,"side","direction")||"") ? "buy":"sell"}">${/BUY|LONG/i.test(pick(t,"side","direction")||"")?"شراء":"بيع"}</span>
        <span><span class="sym">${dash(pick(t,"symbol","instrument"))}</span>
        <span class="meta num"> · ${dash(String(pick(t,"closed_at_utc","closed_at","at_utc")||"").slice(0,16).replace("T"," "))}</span></span>
        <span class="pnl num ${pnl===undefined?"":pnl>0?"v pos":pnl<0?"v neg":""}">${money(pnl)}</span>
      </div>`;
    }, "لا صفقاتٍ مغلقةٍ بعد");
  }

  if (au.status === "fulfilled") {
    renderList("#log", au.value, (e) => `<div class="pos-row" style="grid-template-columns:1fr auto">
        <span style="font-size:13px">${dash(pick(e,"message_ar","summary_ar","event","kind","type"))}</span>
        <span class="meta num">${dash(String(pick(e,"at_utc","created_at","timestamp")||"").slice(5,16).replace("T"," "))}</span>
      </div>`, "السجلُّ فارغ");
  }
}

/* ── البوّابة ────────────────────────────────────────────── */

function showGate(msg) {
  $("#app").hidden = true;
  $("#gate").hidden = false;
  if (msg) $("#gate-msg").textContent = msg;
}

function showApp() {
  $("#gate").hidden = true;
  $("#app").hidden = false;
  poll(refresh, 20000);
  poll(refreshSecondary, 60000);
}

$("#pair").addEventListener("click", async () => {
  const code = $("#code").value.trim();
  if (!code) return;
  const btn = $("#pair"); btn.disabled = true;
  $("#gate-msg").textContent = "يقترن…";
  try {
    /* الحقلُ يُجرَّب على أسمائه المحتملة، والخطأُ 422 يُعرض كما ردَّه
       الخادم — لأن اختراعَ اسمِ حقلٍ أسوأُ من الاعتراف بجهله. */
    let res = null, lastErr = null;
    for (const field of ["pairing_code", "code", "enrollment_code", "token"]) {
      try { res = await api.enroll({ [field]: code }); break; }
      catch (e) { lastErr = e; if (!(e instanceof ApiError) || e.status !== 422) break; }
    }
    if (!res) throw lastErr;
    const t = pick(res, "session_token", "token", "access_token");
    if (!t) throw new Error("لم يُعِد الخادمُ رمزَ جلسة");
    token.set(t);
    showApp();
  } catch (e) {
    const detail = e instanceof ApiError ? JSON.stringify(e.body).slice(0, 200) : e.message;
    $("#gate-msg").textContent = `تعذّر الاقتران — ${detail}`;
  } finally { btn.disabled = false; }
});

$("#unpair").addEventListener("click", () => { token.clear(); location.reload(); });

$("#theme").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "light" ? null : "light";
  if (next) document.documentElement.setAttribute("data-theme", next);
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem("mathrah.theme", next || "dark"); } catch {}
});

try {
  if (localStorage.getItem("mathrah.theme") === "light") document.documentElement.setAttribute("data-theme", "light");
} catch {}

/* ── التنقّل ─────────────────────────────────────────────── */

$$("nav.tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("nav.tabs button").forEach((x) => x.removeAttribute("aria-current"));
  b.setAttribute("aria-current", "page");
  $$("main > section").forEach((s) => { s.hidden = true; });
  $(`#v-${b.dataset.v}`).hidden = false;
  window.scrollTo({ top: 0, behavior: "instant" });
}));

/* ── الإقلاع ─────────────────────────────────────────────── */

if (token.get()) showApp(); else showGate("");

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
