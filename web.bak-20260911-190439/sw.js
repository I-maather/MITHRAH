/* ─────────────────────────────────────────────────────────────
   مِثْراة — عاملُ الخدمة

   يخزّن **الهيكلَ وحده**: HTML وCSS وJS والأيقونات. ولا يخزّن أيَّ
   استجابةٍ من `/api/` أبداً — لأن شاشةً تعرض سعراً قديماً وهي تبدو
   حيّةً أسوأُ من شاشةٍ تقول «لا اتصال». وهذه بالضبط هي الشكوى التي
   سمعتُها من قبل: «متصل بس واقف على قيم قديمة».
   ───────────────────────────────────────────────────────────── */

const V = "mathrah-shell-v1";
const SHELL = [
  "/", "/index.html", "/app.css", "/app.js", "/api.js", "/chart.js",
  "/manifest.webmanifest", "/icon.svg", "/icon-180.png", "/icon-192.png", "/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;      // البياناتُ من الشبكة أو لا شيء
  if (e.request.method !== "GET") return;

  /* الشبكةُ أوّلاً ثم المخزون: التحديثُ يصل فوراً عند النشر، والفتحُ
     بلا شبكةٍ يبقى ممكناً. */
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(V).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/index.html")))
  );
});
