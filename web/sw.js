/* サービスワーカー（Ver2）。
 *
 * 役割は2つだけ。
 * 1. 画面の部品を保存しておき、電波が悪くてもすぐ開けるようにする
 * 2. 画面を閉じている間に届いたお知らせを表示する
 */

const CACHE = "toyocho-v2";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/alarm.mp3",
  "/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // 通信が要る部分（API・実時間の受信）は保存せず、必ずサーバーへ問い合わせる
  if (url.pathname.startsWith("/api/")) return;
  if (event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then(
      (hit) =>
        hit ||
        fetch(event.request).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
          return res;
        })
    )
  );
});

/* 画面を閉じている間に届いたお知らせ */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = {};
  }
  const kind = data.kind === "approaching" ? "まもなく到着" : "到着しました";
  const delay = data.delay_minutes > 0 ? `（遅れ${data.delay_minutes}分）` : "";
  event.waitUntil(
    self.registration.showNotification(`${data.station || ""}駅　${kind}`, {
      body: `${data.line_name || ""}　${data.destination || ""}行　${data.train_number || ""}${delay}`,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      vibrate: [400, 150, 400, 150, 600],
      tag: data.alert_id || "toyocho-alert",
      renotify: true,
      requireInteraction: true,
      data,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) return client.focus();
      }
      return self.clients.openWindow("/");
    })
  );
});
