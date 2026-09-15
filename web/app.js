/* ─────────────────────────────────────────────────────────────
   مِثْراة — الواجهة

   مبنيّةٌ على أنواع `mobile/src/api/types.ts` كما هي، لا على تخمين.

   قاعدةٌ واحدةٌ تحكم كلَّ ما يلي: **لا تخترع قيمة.** الحقلُ الذي يرسله
   الخادم `null` يُعرض شَرطةً، لا صفراً ولا تقديراً. الصفرُ رقمٌ وله معنى؛
   والشَرطةُ تقول «لم يُحسب بعد» — وهذا هو الفرقُ الذي أُخذ على
   `why_no_trade.sh` حين عرض ردَّ 401 على أنه «السوقُ مغلق».
   ───────────────────────────────────────────────────────────── */

import { api, session, enrol, poll, ApiError } from "/api.js";
import { drawCandles } from "/chart.js";

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ── عرضُ القيم ─────────────────────────────────────────── */

const dash = (v) => (v === undefined || v === null || v === "" ? "—" : String(v));
const nOr  = (v) => { const n = Number(v); return Number.isFinite(n) ? n : undefined; };

/** مبلغٌ بإشارته. الخادم يرسل الأرقام المالية **نصّاً** حفاظاً على الدقّة. */
const money = (v) => {
  const n = nOr(v);
  if (n === undefined) return "—";
  const s = Math.abs(n).toFixed(2);
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s;
};
const toneOf = (v) => { const n = nOr(v); return n === undefined ? "" : n > 0 ? "pos" : n < 0 ? "neg" : ""; };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clock = (iso) => (iso ? String(iso).slice(5, 16).replace("T", " ") : "—");
const clearSkeleton = (root) => $$(".skeleton", root).forEach((e) => e.classList.remove("skeleton"));

/* ── الحالة ─────────────────────────────────────────────── */

const S = { symbol: null, resolution: null, candles: null };

function setConn(state, text) {
  $("#conn").className = `chip ${state}`;
  $("#conn-t").textContent = text;
}

/* ── اليوم ──────────────────────────────────────────────── */

function renderStatus(d) {
  const b = d.broker || {};
  $("#env").textContent = [b.name, b.is_demo ? "تجريبي" : "حقيقي"].filter(Boolean).join(" · ") || "—";

  const box = $("#verdict");
  const state = d.system_state || "UNKNOWN";
  const killed = d.kill_switch && d.kill_switch.active;

  /* السطرُ الأوّل هو **سببُ عدم التداول بنصّ الخادم**، لا صياغةٌ من هنا.
     وحين لا يكون هناك سبب، فالنظام يتداول ولا داعي لجملةٍ مصنوعة. */
  const line = killed ? (d.kill_switch.reason_ar || "قاطعُ الطوارئ مفعَّل")
             : (d.no_trade_reason_ar || (state === "RUNNING" ? "النظامُ يعمل ويراقب." : "—"));
  box.querySelector(".line").textContent = line;

  const why = [];
  if (b.connected === false) why.push(b.note_ar || "الوسيطُ غير متصل");
  if (d.locally_paused) why.push("إيقافٌ محليٌّ من الجهاز");
  if (d.last_refresh_utc) why.push(`آخرُ قراءة ${clock(d.last_refresh_utc)}`);
  box.querySelector(".why").textContent = why.join(" · ") || "—";

  const old = box.querySelector(".pill"); if (old) old.remove();
  const pill = document.createElement("span");
  pill.className = "pill " + (killed || state === "KILL_SWITCH" ? "stop"
                   : state === "RUNNING" ? "ok" : "hold");
  pill.textContent = d.system_state_ar || state;
  box.appendChild(pill);
  clearSkeleton(box);
}

function renderFigures(perf, pos) {
  const g = $("#figures");
  const cells = $$(".fig .v", g);

  const realised = perf ? perf.realised_pnl_total : undefined;
  cells[0].textContent = money(realised);
  cells[0].className = `v num ${toneOf(realised)}`;

  /* `open_count === null` يعني «تعذّرت القراءة ولا شيء في الدفتر» —
     وليس «لا مراكز». الشَرطةُ تقول ذلك والصفرُ يكذب. */
  cells[1].textContent = pos ? dash(pos.open_count) : "—";

  const w = perf ? perf.wins : undefined, l = perf ? perf.losses : undefined;
  cells[2].textContent = (w == null && l == null) ? "—" : `${w ?? "—"} / ${l ?? "—"}`;
  clearSkeleton(g);
}

function renderPositions(d) {
  const box = $("#positions");
  const rows = (d && d.positions) || [];

  if (!rows.length) {
    box.innerHTML = `<div class="empty">${
      d && d.has_position === null
        ? "تعذّرت قراءةُ المراكز — ولا شيءَ في الدفتر. هذه «لا أعرف» لا «لا مراكز»."
        : "لا مراكزَ مفتوحة الآن"}</div>`;
    return;
  }

  const banner =
    d.reconciliation === "RECONNECTING"
      ? `<div class="rowbanner bad">تعذّرت المطابقةُ مع الوسيط — يُعرَض آخرُ المعروف.</div>`
      : d.stale_count > 0
        ? `<div class="rowbanner">${d.stale_count} مركزٌ لم يُؤكَّد في هذه القراءة.</div>`
        : "";

  box.innerHTML = banner + rows.map((p) => {
    const sell = /بيع/.test(p.direction_ar || "");
    const meta = [p.size_display, p.entry_price ? `دخول ${p.entry_price}` : null,
                  p.risk_at_stop ? `مخاطرة ${p.risk_at_stop}` : null]
                 .filter(Boolean).join(" · ");
    const flags = [];
    if (p.protection_held_by_broker === false) flags.push(`<span class="flag bad">بلا وقفٍ عند الوسيط</span>`);
    if (p.reconciliation === "STALE") flags.push(`<span class="flag">غير مؤكَّد</span>`);
    return `<div class="pos-row">
      <span class="side ${sell ? "sell" : "buy"}">${esc(p.direction_ar || "—")}</span>
      <span>
        <span class="sym">${esc(p.instrument || p.instrument_ar || "—")}</span>
        <span class="meta num">${esc(meta)}</span>
        ${flags.join(" ")}
      </span>
      <span class="pnl num ${toneOf(p.unrealised_pnl)}">${money(p.unrealised_pnl)}</span>
    </div>`;
  }).join("");
}

function renderCandles(d) {
  S.candles = d;
  const symbols = d.symbols || Object.keys(d.instruments || {});
  if (!symbols.length) return;
  if (!S.symbol || !symbols.includes(S.symbol)) S.symbol = symbols[0];
  S.resolution = d.decision_resolution || (d.resolutions || [])[0] || null;

  const tabs = $("#symtabs");
  const want = symbols.join("|");
  if (tabs.dataset.keys !== want) {
    tabs.dataset.keys = want;
    tabs.innerHTML = symbols.map((s) =>
      `<button data-s="${esc(s)}" aria-pressed="${s === S.symbol}">${esc(s)}</button>`).join("");
    tabs.onclick = (e) => {
      const b = e.target.closest("button"); if (!b) return;
      S.symbol = b.dataset.s;
      $$("#symtabs button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.s === S.symbol)));
      paintChart();
    };
  }
  $("#chart-note").textContent = d.note_ar || "";
  paintChart();
}

function paintChart() {
  const d = S.candles; if (!d || !S.symbol) return;
  const byRes = (d.instruments || {})[S.symbol] || {};
  const res = (S.resolution && byRes[S.resolution]) ? S.resolution : Object.keys(byRes)[0];
  const raw = byRes[res] || [];

  const bars = raw.map((b) => ({
    o: Number(b.o), h: Number(b.h), l: Number(b.l), c: Number(b.c), t: b.t,
  })).filter((b) => Number.isFinite(b.o) && Number.isFinite(b.c));

  const liveRec = (d.live || {})[S.symbol];
  const live = liveRec ? nOr(liveRec.price) : undefined;
  const lastStr = raw.length ? raw[raw.length - 1].c : "";
  const shown = live ?? (bars.length ? bars[bars.length - 1].c : undefined);

  /* عددُ الخانات من السعر نفسه: الذهبُ خانتان والفوركس خمس، وقاعدةٌ
     واحدةٌ تخون إحداهما. */
  const src = liveRec ? String(liveRec.price) : String(lastStr);
  const dec = src.includes(".") ? src.split(".")[1].length : 2;
  const digits = Math.max(2, Math.min(5, dec));

  $("#px").textContent = shown === undefined ? "—" : Number(shown).toFixed(digits);
  $("#res").textContent = res ? `${res}${res === d.decision_resolution ? " · إطارُ القرار" : ""}` : "";

  const first = bars.length ? bars[Math.max(0, bars.length - 60)].o : undefined;
  const dEl = $("#dx");
  if (first !== undefined && shown !== undefined && first !== 0) {
    const pct = ((shown - first) / first) * 100;
    dEl.textContent = `${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(2)}%`;
    dEl.style.color = pct >= 0 ? "var(--pos)" : "var(--neg)";
  } else dEl.textContent = "";

  /* المستوياتُ تخصّ أداةً واحدة. رسمُها على أداةٍ أخرى كذبٌ صامت. */
  const lv = d.levels || {};
  const levels = (lv.symbol === S.symbol) ? [
    { price: nOr(lv.entry),  label: "دخول",  tone: "neutral" },
    { price: nOr(lv.stop),   label: "وقف",   tone: "neg" },
    { price: nOr(lv.target), label: "هدف",   tone: "pos" },
  ].filter((x) => x.price !== undefined) : [];

  drawCandles($("#chart"), bars, { levels, live, digits });
}

/* ── المخاطرة ───────────────────────────────────────────── */

const row = (k, v, cls = "") =>
  `<div class="kv"><span class="k">${esc(k)}</span><span class="v num ${cls}">${esc(dash(v))}</span></div>`;

function renderRisk(d) {
  const box = $("#riskbox");
  const p = d.portfolio || {};
  const cur = d.currency || "";

  const notes = [];
  if (d.two_loss_lock_active) notes.push(`<div class="rowbanner bad">قفلُ الخسارتَين مفعَّل الآن.</div>`);
  if (p.diverged) notes.push(`<div class="rowbanner">${esc(p.note_ar || "المرجعيُّ يخالف رصيدَ الوسيط.")}</div>`);

  box.innerHTML = `<h2>سياسةُ المخاطرة${cur ? ` · ${esc(cur)}` : ""}</h2>`
    + (d.profile_binding_ar ? `<p class="note">${esc(d.profile_binding_ar)}</p>` : "")
    + notes.join("")
    + row("الملف", d.profile_name_ar || d.profile)
    + row("المرجعيّ (تُحسب منه الحدود)", p.baseline_equity)
    + row("رصيدُ الوسيط", p.broker_equity)
    + row("الحالي", p.current_equity)
    + row("أقصى مخاطرةٍ للصفقة", d.max_risk_per_trade)
    + row("استُهلك اليوم", d.risk_used_today)
    + row("المتبقّي اليوم", d.risk_remaining_today)
    + row("حدُّ اليوم", d.max_daily_loss)
    + row("حدُّ الأسبوع", d.max_weekly_loss)
    + row("المسافةُ إلى قاطع الطوارئ", d.distance_to_kill_switch)
    + row("المراكزُ المفتوحة", `${dash(d.open_positions)} / ${dash(d.max_open_positions)}`)
    + row("أوامرُ الدخول اليوم", `${dash(d.entry_orders_today)} / ${dash(d.max_entry_orders_per_day)}`)
    + row("خسائرُ متتالية", d.consecutive_losses);
}

function renderParticipation(d) {
  const box = $("#funnel");
  if (!d.available) {
    box.innerHTML = `<h2>مسارُ الفرص</h2><div class="empty">${esc(d.reason_ar || "غيرُ متاح")}</div>`;
    return;
  }
  const steps = (d.steps || []).map((s) =>
    `<div class="kv${s.reached ? "" : " off"}">
       <span class="k">${esc(s.label_ar)}</span>
       <span class="v num">${esc(s.count)}</span>
     </div>`).join("");

  const reasons = (d.top_reasons || []).slice(0, 5).map((r) =>
    `<div class="kv small"><span class="k">${esc(r.code)}</span><span class="v num">${r.count}</span></div>`).join("");

  const isolated = (d.isolated_instruments || []).map((i) =>
    `<span class="flag">${esc(i.symbol)} · ${esc(i.reason_code)}</span>`).join(" ");

  box.innerHTML = `<h2>مسارُ الفرص · ${esc(d.trading_day || "")}</h2>`
    + steps
    + `<p class="note">انهار عند <b>${esc(d.collapse_stage_ar || d.collapse_stage)}</b> — ${esc(d.blamed_on_ar || d.blamed_on)}</p>`
    + (isolated ? `<p class="note">أدواتٌ معزولة: ${isolated}</p>` : "")
    + (reasons ? `<h2 style="margin-top:14px">أكثرُ أسباب الرفض</h2>${reasons}` : "")
    + (d.note_ar ? `<p class="note">${esc(d.note_ar)}</p>` : "");
}

/* ── الصفقات والسجل ─────────────────────────────────────── */

function renderTrades(d) {
  const box = $("#trades");
  if (d.unavailable) {
    box.innerHTML = `<div class="empty">لم تُقرأ الصفقات — القائمةُ الفارغة هنا ليست «لا صفقات».</div>`;
    return;
  }
  const list = d.trades || [];
  if (!list.length) { box.innerHTML = `<div class="empty">لا صفقاتٍ مغلقةٍ بعد</div>`; return; }

  const head = d.realised_pnl_total != null
    ? `<div class="rowbanner">المحقَّقُ الكلّي <b class="num ${toneOf(d.realised_pnl_total)}">${money(d.realised_pnl_total)}</b></div>`
    : "";

  box.innerHTML = head + list.map((t) => {
    const sell = /بيع/.test(t.direction_ar || "");
    const meta = [clock(t.closed_utc), t.outcome_ar, t.exit_reason_ar].filter(Boolean).join(" · ");
    return `<div class="pos-row">
      <span class="side ${sell ? "sell" : "buy"}">${esc(t.direction_ar || "—")}</span>
      <span>
        <span class="sym">${esc(t.instrument || t.instrument_ar || "—")}</span>
        <span class="meta">${esc(meta)}</span>
      </span>
      <span class="pnl num ${toneOf(t.realised_pnl)}">${money(t.realised_pnl)}</span>
    </div>`;
  }).join("");
}

function renderAudit(d) {
  const box = $("#log");
  const rows = d.entries || [];
  if (!rows.length) { box.innerHTML = `<div class="empty">السجلُّ فارغ</div>`; return; }
  box.innerHTML = rows.slice(0, 60).map((e) =>
    `<div class="pos-row log">
       <span class="side ${e.success ? "buy" : "sell"}">${e.success ? "تمّ" : "رُفض"}</span>
       <span><span class="sym small">${esc(e.action)}</span>
       <span class="meta">${esc(e.detail_ar || "")}</span></span>
       <span class="meta num">${clock(e.at_utc)}</span>
     </div>`).join("");
}

/* ── الدورة ─────────────────────────────────────────────── */

let expired = false;

function handle(results) {
  const gone = results.some((r) => r.status === "rejected"
    && r.reason instanceof ApiError && r.reason.status === 401);
  if (gone && !expired) { expired = true; session.clear(); showGate("انتهت الجلسة — أعيدي الاقتران."); }
  return !gone;
}

async function refreshMain() {
  const r = await Promise.allSettled([api.status(), api.positions(), api.performance(), api.candles()]);
  if (!handle(r)) return;
  const ok = r.filter((x) => x.status === "fulfilled");
  if (!ok.length) { setConn("down", "لا اتصال"); return; }
  setConn("live", "حيّ");

  const [st, ps, pf, cd] = r;
  if (st.status === "fulfilled") renderStatus(st.value.data);
  if (ps.status === "fulfilled") renderPositions(ps.value.data);
  renderFigures(pf.status === "fulfilled" ? pf.value.data : null,
                ps.status === "fulfilled" ? ps.value.data : null);
  if (cd.status === "fulfilled") renderCandles(cd.value.data);
}

async function refreshSecondary() {
  const r = await Promise.allSettled([api.risk(), api.participation(), api.trades(), api.audit()]);
  if (!handle(r)) return;
  const [rk, pt, tr, au] = r;
  if (rk.status === "fulfilled") renderRisk(rk.value.data);
  if (pt.status === "fulfilled") renderParticipation(pt.value.data);
  if (tr.status === "fulfilled") renderTrades(tr.value.data);
  if (au.status === "fulfilled") renderAudit(au.value.data);
}

/* ── البوّابة ───────────────────────────────────────────── */

function showGate(msg) {
  $("#app").hidden = true;
  $("#gate").hidden = false;
  if (msg) $("#gate-msg").textContent = msg;
}

let started = false;
function showApp() {
  $("#gate").hidden = true;
  $("#app").hidden = false;
  if (started) return;
  started = true;
  poll(refreshMain, 20000);
  poll(refreshSecondary, 60000);
}

$("#pair").addEventListener("click", async () => {
  const btn = $("#pair");
  const text = $("#code").value.trim();
  if (!text) return;
  btn.disabled = true;
  $("#gate-msg").textContent = "يقترن…";
  const res = await enrol(text);
  btn.disabled = false;
  if (res.ok) { expired = false; $("#code").value = ""; $("#gate-msg").textContent = ""; showApp(); }
  else $("#gate-msg").textContent = res.ar;
});

$("#unpair").addEventListener("click", () => { session.clear(); location.reload(); });

$("#theme").addEventListener("click", () => {
  const light = document.documentElement.getAttribute("data-theme") === "light";
  if (light) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", "light");
  try { localStorage.setItem("mathrah.theme", light ? "dark" : "light"); } catch {}
});
try { if (localStorage.getItem("mathrah.theme") === "light") document.documentElement.setAttribute("data-theme", "light"); } catch {}

/* ── التنقّل ────────────────────────────────────────────── */

$$("nav.tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("nav.tabs button").forEach((x) => x.removeAttribute("aria-current"));
  b.setAttribute("aria-current", "page");
  $$("main > section").forEach((s) => { s.hidden = true; });
  $(`#v-${b.dataset.v}`).hidden = false;
  window.scrollTo(0, 0);
}));

/* ── الإقلاع ────────────────────────────────────────────── */

if (session.hasSession()) showApp(); else showGate("");
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
