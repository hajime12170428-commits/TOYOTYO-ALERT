/* サービスワーカー（Ver2）。
 *
 * 役割は2つだけ。
 * 1. 画面の部品を保存しておき、電波が悪くてもすぐ開けるようにする
 * 2. 画面を閉じている間に届いたお知らせを表示する
 */

// 番号を上げると、利用者の端末に残っている古い保存が自動で捨てられる。
// 画面のファイルを直したときは必ず上げること（上げないと古い画面が出続ける）。
const CACHE = "toyocho-v3";
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

  // 画面本体（ページの読み込み）は「まずサーバー、だめなら保存」。
  // 逆にすると、画面を直しても利用者に古い画面が出続けてしまうため。
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 部品（CSS・JS・音・アイコン）は「まず保存、なければサーバー」（表示を速くするため）
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
