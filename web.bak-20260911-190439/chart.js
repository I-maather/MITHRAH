/* ─────────────────────────────────────────────────────────────
   مِثْراة — رسمُ الشموع
   نفسُ القرارات المعتمدة في نسخة الجوال، لا نسخةٌ ثانيةٌ بذوقٍ آخر:

   · لا خطوطَ شبكة. السُلَّمُ السعري على اليسار يحمل المقياس وحده،
     فتسعةُ خطوطٍ صارت أربعة، والرسمُ صار يُقرأ بدل أن يُزاحَم.
   · الشمعةُ الصاعدة مُفرَّغة والهابطة مصمتة، والحدُّ ملوّن. الصعودُ
     يُرى بالخفّة والهبوطُ بالثقل — واللونُ وحده لا يكفي لمن لا يفرّق
     بين الأحمر والأخضر.
   · خطُّ السعر الحيّ ينبض. الحياةُ تُرى في نقطةٍ واحدةٍ متحرّكة،
     لا في رسمٍ يُعاد بناؤه كلَّ ثانية.
   ───────────────────────────────────────────────────────────── */

const NS = "http://www.w3.org/2000/svg";
const el = (n, a = {}) => {
  const e = document.createElementNS(NS, n);
  for (const k in a) e.setAttribute(k, a[k]);
  return e;
};

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/**
 * @param {SVGElement} svg
 * @param {{o:number,h:number,l:number,c:number,t?:string}[]} bars
 * @param {{levels?: {price:number,label?:string}[], live?: number|null, digits?: number}} opts
 */
export function drawCandles(svg, bars, opts = {}) {
  const { levels = [], live = null, digits = 5 } = opts;
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const W = 360, H = 190;           // إحداثياتٌ داخليةٌ ثابتة، والمقياسُ بالعرض
  const PAD_L = 6, PAD_R = 60, PAD_T = 10, PAD_B = 16;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");

  if (!bars || bars.length < 2) {
    const t = el("text", {
      x: W / 2, y: H / 2, fill: css("--ink-3"),
      "font-size": "11", "text-anchor": "middle",
    });
    t.textContent = "لا توجد شموعٌ بعد";
    svg.appendChild(t);
    return;
  }

  const shown = bars.slice(-60);
  let lo = Infinity, hi = -Infinity;
  for (const b of shown) { if (b.l < lo) lo = b.l; if (b.h > hi) hi = b.h; }
  for (const lv of levels) { if (lv.price < lo) lo = lv.price; if (lv.price > hi) hi = lv.price; }
  const span = (hi - lo) || Math.max(Math.abs(hi) * 1e-4, 1e-6);
  lo -= span * 0.08; hi += span * 0.08;

  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const y = (p) => PAD_T + (hi - p) / (hi - lo) * plotH;
  const step = plotW / shown.length;
  const bw = Math.max(1.6, Math.min(9, step * 0.62));

  const POS = css("--pos"), NEG = css("--neg"), INK3 = css("--ink-3"), LINE = css("--line");

  /* ── السُلَّمُ السعري: أربعُ درجاتٍ وحدها ──
     ودرجةٌ تقع على ارتفاع السعر الحيّ تُحذف: الرقمان يتراكبان في
     نفس الممرّ الضيّق فيصيران لطخة. الحيُّ أولى بالمكان. */
  const liveY = (live != null && Number.isFinite(live)) ? y(live) : null;
  const ladder = el("g");
  for (let i = 0; i <= 3; i++) {
    const p = hi - (hi - lo) * (i / 3);
    const yy = y(p);
    if (liveY !== null && Math.abs(yy - liveY) < 15) continue;
    const tx = el("text", {
      x: W - PAD_R + 7, y: yy + 3.4, fill: INK3,
      "font-size": "8.5", "text-anchor": "start",
      "font-family": "ui-monospace, SFMono-Regular, monospace",
    });
    tx.textContent = p.toFixed(digits);
    ladder.appendChild(tx);
  }

  /* ── المستويات: خافتةٌ لأنها سياقٌ لا موضوع ── */
  for (const lv of levels) {
    if (lv.price < lo || lv.price > hi) continue;
    const yy = y(lv.price);
    svg.appendChild(el("line", {
      x1: PAD_L, x2: W - PAD_R, y1: yy, y2: yy,
      stroke: lv.tone === "neg" ? NEG : lv.tone === "pos" ? POS : LINE,
      "stroke-width": 1, "stroke-dasharray": "3 5", opacity: 0.45,
    }));
    if (lv.label) {
      const t = el("text", {
        x: PAD_L + 3, y: yy - 4, fill: INK3, "font-size": "8", opacity: 0.85,
      });
      t.textContent = lv.label;
      svg.appendChild(t);
    }
  }

  /* ── الشموع ── */
  const g = el("g");
  shown.forEach((b, i) => {
    const cx = PAD_L + step * (i + 0.5);
    const rising = b.c >= b.o;
    const tone = rising ? POS : NEG;

    g.appendChild(el("line", {
      x1: cx, x2: cx, y1: y(b.h), y2: y(b.l),
      stroke: tone, "stroke-width": 1, opacity: 0.9,
    }));

    const yo = y(b.o), yc = y(b.c);
    const top = Math.min(yo, yc);
    const hgt = Math.max(0.9, Math.abs(yc - yo));
    g.appendChild(el("rect", {
      x: cx - bw / 2, y: top, width: bw, height: hgt,
      rx: Math.min(1.4, bw / 4),
      fill: rising ? "none" : tone,
      stroke: tone, "stroke-width": 1,
    }));
  });
  svg.appendChild(g);

  /* ── السعرُ الحيّ ── */
  if (live != null && Number.isFinite(live) && live >= lo && live <= hi) {
    const yy = y(live);
    svg.appendChild(el("line", {
      x1: PAD_L, x2: W - PAD_R, y1: yy, y2: yy,
      stroke: css("--accent"), "stroke-width": 1,
      "stroke-dasharray": "2 4", opacity: 0.5,
    }));
    /* نقطةٌ نابضةٌ وحدها. **لا لافتةَ سعرٍ هنا:** السعرُ مكتوبٌ كبيراً
       فوق الرسم أصلاً، واللافتةُ كانت تركب على أرقام السُلَّم فتصير
       الزاويةُ اليمنى عجينةً — وهو نفسُ الازدحام الذي أزلناه من هذا
       الرسم مرّةً من قبل. */
    const pulse = el("circle", {
      cx: W - PAD_R, cy: yy, r: 3, fill: css("--accent"),
    });
    svg.appendChild(pulse);
    const halo = el("circle", {
      cx: W - PAD_R, cy: yy, r: 3, fill: "none",
      stroke: css("--accent"), "stroke-width": 1, opacity: 0.6,
    });
    halo.appendChild(el("animate", {
      attributeName: "r", values: "3;9;3", dur: "2.6s", repeatCount: "indefinite",
    }));
    halo.appendChild(el("animate", {
      attributeName: "opacity", values: "0.6;0;0.6", dur: "2.6s", repeatCount: "indefinite",
    }));
    svg.appendChild(halo);
  }

  svg.appendChild(ladder);   // آخِرُ ما يُرسم: الأرقامُ فوق كلِّ شيء

  /* ── التأشيرُ باللمس: يظهر بعد ٢٤٠ مللي، ويُلغى بحركةٍ فوق ٦ بكسل ── */
  attachCursor(svg, shown, { PAD_L, PAD_R, step, y, W, H, digits });
}

function attachCursor(svg, shown, m) {
  const layer = el("g", { opacity: "0" });
  const vline = el("line", { y1: 0, y2: m.H, stroke: css("--ink-2"), "stroke-width": 0.8, opacity: 0.55 });
  const box = el("rect", { width: 96, height: 34, rx: 7, fill: css("--bg"), stroke: css("--line") });
  const l1 = el("text", { "font-size": "8.5", fill: css("--ink-2") });
  const l2 = el("text", { "font-size": "9.5", fill: css("--ink"), "font-family": "ui-monospace, monospace" });
  layer.append(vline, box, l1, l2);
  svg.appendChild(layer);

  let hold = null, down = null, active = false;

  const show = (clientX) => {
    const r = svg.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * m.W;
    let i = Math.floor((px - m.PAD_L) / m.step);
    i = Math.max(0, Math.min(shown.length - 1, i));
    const b = shown[i];
    const cx = m.PAD_L + m.step * (i + 0.5);
    vline.setAttribute("x1", cx); vline.setAttribute("x2", cx);
    const bx = Math.max(2, Math.min(m.W - 98, cx - 48));
    box.setAttribute("x", bx); box.setAttribute("y", 4);
    l1.setAttribute("x", bx + 7); l1.setAttribute("y", 16);
    l2.setAttribute("x", bx + 7); l2.setAttribute("y", 29);
    l1.textContent = b.t ? String(b.t).slice(5, 16).replace("T", " ") : `شمعة ${i + 1}`;
    const d = m.digits;
    l2.textContent = `${b.o.toFixed(d)} → ${b.c.toFixed(d)}`;
    layer.setAttribute("opacity", "1");
    active = true;
  };
  const hide = () => { layer.setAttribute("opacity", "0"); active = false; clearTimeout(hold); };

  svg.addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    down = { x: t.clientX, y: t.clientY };
    hold = setTimeout(() => show(t.clientX), 240);
  }, { passive: true });

  svg.addEventListener("touchmove", (e) => {
    const t = e.touches[0];
    if (!active) {
      if (down && Math.hypot(t.clientX - down.x, t.clientY - down.y) > 6) clearTimeout(hold);
      return;
    }
    e.preventDefault();
    show(t.clientX);
  }, { passive: false });

  svg.addEventListener("touchend", hide, { passive: true });
  svg.addEventListener("touchcancel", hide, { passive: true });
  svg.addEventListener("mousemove", (e) => show(e.clientX));
  svg.addEventListener("mouseleave", hide);
}
