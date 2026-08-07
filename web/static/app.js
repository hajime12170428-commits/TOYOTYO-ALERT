/* TOYOCHO ALERT Ver2 — 画面の動き。
 *
 * 組み立て（ビルド）の仕組みを使わない素のJavaScriptで書いてある。
 * 画面が3つだけの小さな作りのため、部品を足すより保守が軽く、起動も速いため。
 */

const $ = (id) => document.getElementById(id);
const api = (path, options) =>
  fetch(path, { credentials: "same-origin", ...options }).then(async (r) => {
    if (r.status === 204) return null;
    const body = await r.json().catch(() => null);
    if (!r.ok) throw new Error(body?.detail || "通信に失敗しました。");
    return body;
  });

let LINES = [];
let audioReady = false;
let alarmAudio = null;

/* ---------- 画面の切り替え ---------- */

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`view-${name}`).classList.add("active");
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === name)
  );
  if (name === "watch") loadWatches();
  if (name === "history") loadHistory();
}
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => showView(tab.dataset.view))
);

/* ---------- 路線と駅 ---------- */

async function loadLines() {
  // 路線と駅は変わらないため、端末に保存して次回は通信しない
  const cached = localStorage.getItem("lines");
  if (cached) {
    LINES = JSON.parse(cached);
    fillLineOptions();
  }
  try {
    LINES = await api("/api/lines");
    localStorage.setItem("lines", JSON.stringify(LINES));
    fillLineOptions();
  } catch (e) {
    if (!cached) console.warn("路線の取得に失敗:", e);
  }
}

function fillLineOptions() {
  const select = $("f-line");
  const current = select.value;
  select.innerHTML = LINES.map((l) => `<option value="${l.id}">${l.name}</option>`).join("");
  if (current) select.value = current;
  fillStationOptions();
}

function fillStationOptions() {
  const line = LINES.find((l) => l.id === $("f-line").value);
  if (!line) return;
  $("f-station").innerHTML = line.stations.map((s) => `<option>${s}</option>`).join("");
  $("f-direction").innerHTML =
    '<option value="">すべて</option>' +
    line.directions.map((d) => `<option>${d}</option>`).join("");
  $("dest-list").innerHTML = line.stations.map((s) => `<option>${s}</option>`).join("");
}
$("f-line").addEventListener("change", fillStationOptions);

/* ---------- 見張りの一覧 ---------- */

async function loadWatches() {
  const items = await api("/api/subscriptions").catch(() => []);
  const list = $("watch-list");
  $("watch-empty").hidden = items.length > 0;
  list.innerHTML = items
    .map((s) => {
      const line = LINES.find((l) => l.id === s.line_id);
      const cond = [
        s.direction || "全方面",
        s.destination ? `${s.destination}行` : "全行先",
        s.notify_on.includes("approaching") ? "接近時に通知" : "到着時に通知",
      ].join("・");
      return `<li class="card ${s.active ? "" : "off"}" style="border-left-color:${line?.color || "#38bdf8"}">
        <p class="card-title">${s.line_name}　${s.station_id}駅</p>
        <p class="card-sub">${cond}</p>
        <div class="card-actions">
          <button class="mini" onclick="toggleWatch('${s.id}', ${!s.active})">${s.active ? "一時停止" : "再開"}</button>
          <button class="mini danger" onclick="deleteWatch('${s.id}')">削除</button>
        </div>
      </li>`;
    })
    .join("");
}

async function toggleWatch(id, active) {
  await api(`/api/subscriptions/${id}?active=${active}`, { method: "PATCH" });
  loadWatches();
}

async function deleteWatch(id) {
  if (!confirm("この見張りを削除しますか？")) return;
  await api(`/api/subscriptions/${id}`, { method: "DELETE" });
  loadWatches();
}

/* ---------- 見張りの追加 ---------- */

$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("add-error").hidden = true;
  try {
    await api("/api/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        line_id: $("f-line").value,
        station_id: $("f-station").value,
        direction: $("f-direction").value || null,
        destination: $("f-destination").value.trim() || null,
        notify_on: $("f-notify").value.split(","),
      }),
    });
    $("f-destination").value = "";
    showView("watch");
  } catch (err) {
    $("add-error").textContent = err.message;
    $("add-error").hidden = false;
  }
});

/* ---------- 履歴 ---------- */

async function loadHistory() {
  const items = await api("/api/alerts?limit=50").catch(() => []);
  $("history-empty").hidden = items.length > 0;
  $("history-list").innerHTML = items
    .map((a) => {
      const t = new Date(a.fired_at + "Z").toLocaleString("ja-JP", {
        month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
      });
      const kind = a.kind === "approaching" ? "接近" : "到着";
      const delay = a.delay_minutes > 0 ? `　遅れ${a.delay_minutes}分` : "";
      return `<li class="card">
        <p class="card-title">${a.station_id}　${kind}</p>
        <p class="card-sub">${t}　${a.line_name}　${a.destination}行　${a.train_number}${delay}</p>
      </li>`;
    })
    .join("");
}

/* ---------- 通知を受け取る（画面を開いている間） ---------- */

function connectStream() {
  const source = new EventSource("/api/stream");
  source.onopen = () => $("conn").classList.add("online");
  source.onerror = () => $("conn").classList.remove("online");
  source.onmessage = (e) => {
    try {
      fireAlarm(JSON.parse(e.data));
    } catch (err) {
      console.warn("通知の読み取りに失敗:", err);
    }
  };
  // EventSourceは切れても自動でつなぎ直すため、こちらでの再接続処理は不要
}

/* ---------- アラーム ---------- */

function fireAlarm(alert) {
  $("alarm-kind").textContent = alert.kind === "approaching" ? "まもなく到着" : "到着しました";
  $("alarm-station").textContent = `${alert.station}駅`;
  const delay = alert.delay_minutes > 0 ? `　遅れ${alert.delay_minutes}分` : "";
  $("alarm-detail").textContent =
    `${alert.line_name}　${alert.destination}行　${alert.train_number}${delay}`;
  $("alarm").hidden = false;
  $("alarm").dataset.alertId = alert.alert_id;

  if (navigator.vibrate) navigator.vibrate([400, 150, 400, 150, 600]);
  playSound();
  keepScreenAwake();
}

$("alarm-stop").addEventListener("click", () => {
  $("alarm").hidden = true;
  stopSound();
  const id = $("alarm").dataset.alertId;
  if (id) api(`/api/alerts/${id}/ack`, { method: "POST" }).catch(() => {});
  releaseScreen();
});

function playSound() {
  if (!audioReady || !alarmAudio) return;
  alarmAudio.currentTime = 0;
  alarmAudio.loop = true;
  alarmAudio.play().catch(() => {});
}
function stopSound() {
  if (alarmAudio) { alarmAudio.pause(); alarmAudio.loop = false; }
}

/* 画面が消えないようにする（アラーム表示中だけ） */
let wakeLock = null;
async function keepScreenAwake() {
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch {}
}
function releaseScreen() {
  wakeLock?.release().catch(() => {});
  wakeLock = null;
}

/* ---------- 初回の許可（音・OS通知） ---------- */
/* 携帯では、利用者が一度ボタンを押さないと音を鳴らせない決まりがあるため、
   最初に1回だけ無音を再生して「鳴らせる状態」にしておく。 */

async function setupPermissions() {
  alarmAudio = new Audio("/static/alarm.mp3");
  try {
    alarmAudio.volume = 0;
    await alarmAudio.play();
    alarmAudio.pause();
    alarmAudio.currentTime = 0;
    alarmAudio.volume = 1;
    audioReady = true;
  } catch {
    audioReady = false;
  }
  localStorage.setItem("setup_done", "1");
  await registerPush();
}

async function registerPush() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    const key = await api("/api/push/key");
    if (!key.enabled) return;
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return;

    const reg = await navigator.serviceWorker.ready;
    const sub =
      (await reg.pushManager.getSubscription()) ||
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key.public_key),
      }));
    const json = sub.toJSON();
    await api("/api/push/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        endpoint: json.endpoint,
        p256dh: json.keys.p256dh,
        auth: json.keys.auth,
      }),
    });
  } catch (e) {
    console.warn("お知らせの登録に失敗:", e);
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

$("setup-ok").addEventListener("click", async () => {
  await setupPermissions();
  $("setup").hidden = true;
});
$("setup-skip").addEventListener("click", () => {
  localStorage.setItem("setup_done", "1");
  $("setup").hidden = true;
});

/* ---------- 起動 ---------- */

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("SW登録:", e));
  }
  await loadLines();
  await loadWatches();
  connectStream();
  if (!localStorage.getItem("setup_done")) {
    $("setup").hidden = false;
  } else {
    alarmAudio = new Audio("/static/alarm.mp3");
    audioReady = true;
  }
}
boot();
