const alarmScreen = document.getElementById("alarmScreen");
const alarm = document.getElementById("alarm");
const audioNotice = document.getElementById("audioNotice");

const lineText = document.getElementById("lineText");
const stationText = document.getElementById("stationText");
const trainText = document.getElementById("trainText");

const lineSelect = document.getElementById("lineSelect");
const stationSelect = document.getElementById("stationSelect");
const destinationSelect = document.getElementById("destinationSelect");
const trainList = document.getElementById("trainList");
const trainInput = document.getElementById("trainInput");
const trackingArea = document.getElementById("trackingArea");

const DEFAULT_LINE = "Tozai";
const DEFAULT_STATION = "木場";

// /lines から取得した路線マスタ
let lines = [];

// 直近の /status 応答(監視切替の確認ダイアログに使う)
let lastStatus = null;

let alarmPlaying = false;


// ----------------------
// 路線データ読み込み・フォーム構築
// ----------------------
function fillSelect(select, values, selected, emptyLabel) {

    select.innerHTML = "";

    if (emptyLabel) {

        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = emptyLabel;
        select.appendChild(opt);

    }

    values.forEach(v => {

        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);

    });

    if (selected !== null &&
        [...select.options].some(o => o.value === selected)) {

        select.value = selected;

    }

}


function currentLine() {

    return lines.find(l => l.id === lineSelect.value) || null;

}


// 選択中の路線カラーをセレクトボックスに反映する
function updateLineColor() {

    const line = currentLine();

    lineSelect.style.borderLeft =
        line ? `10px solid ${line.color}` : "";

}


// 路線に合わせて駅・行先の選択肢を作り直す
function populateLineFields(savedStation, savedDestination) {

    const line = currentLine();

    if (!line) return;

    const station =
        savedStation !== undefined
            ? savedStation
            : (line.id === DEFAULT_LINE ? DEFAULT_STATION : null);

    fillSelect(stationSelect, line.stations, station);
    fillSelect(destinationSelect, line.destinations,
        savedDestination !== undefined ? savedDestination : "",
        "指定なし(全行先)");

    updateLineColor();

}


async function loadLines() {

    try {

        const res = await fetch("/lines");
        lines = await res.json();

        lineSelect.innerHTML = "";

        lines.forEach(l => {

            const opt = document.createElement("option");
            opt.value = l.id;
            opt.textContent = l.name;
            lineSelect.appendChild(opt);

        });

        const savedLine = localStorage.getItem("line") || DEFAULT_LINE;

        if ([...lineSelect.options].some(o => o.value === savedLine)) {
            lineSelect.value = savedLine;
        }

        if (lineSelect.value === localStorage.getItem("line")) {

            populateLineFields(
                localStorage.getItem("station") || undefined,
                localStorage.getItem("destination") || undefined
            );

        } else {

            populateLineFields();

        }

        loadTrains();

    } catch (e) {

        console.log("路線データの取得に失敗:", e);

    }

}


lineSelect.addEventListener("change", () => {
    populateLineFields();
    loadTrains();
});

destinationSelect.addEventListener("change", () => loadTrains());

window.addEventListener("load", loadLines);


// ----------------------
// 在線列車一覧(クリックで監視開始)
// ----------------------
async function loadTrains() {

    const line = currentLine();

    if (!line) return;

    try {

        const res = await fetch(
            "/trains?line=" + encodeURIComponent(line.id)
        );

        if (!res.ok) throw new Error("HTTP " + res.status);

        renderTrains(await res.json());

    } catch (e) {

        console.log("在線一覧の取得に失敗:", e);
        trainList.textContent = "列車一覧を取得できませんでした";

    }

}


function renderTrains(trains) {

    // 行先を選択している場合はその行先の列車だけ表示する
    const dest = destinationSelect.value;
    const filtered = dest
        ? trains.filter(t => t.destination === dest)
        : trains;

    trainList.innerHTML = "";

    if (filtered.length === 0) {
        trainList.textContent = "現在走行中の対象列車はありません";
        return;
    }

    filtered.forEach(t => {

        const btn = document.createElement("button");
        btn.type = "button";  // フォーム送信はクリックハンドラ側で行う
        btn.className = "trainItem";

        const number = document.createElement("span");
        number.className = "trainNumber";
        number.textContent = t.number;

        const meta = document.createElement("span");
        meta.className = "trainMeta";

        let info = `${t.type} ${t.destination}行 / ${(t.now || []).join("〜")}`;
        if (t.delay) info += ` / ${t.delay}`;
        meta.textContent = info;

        btn.appendChild(number);
        btn.appendChild(meta);

        btn.addEventListener("click", () => {
            trainInput.value = t.number;
            document.querySelector("form").requestSubmit();
        });

        trainList.appendChild(btn);

    });

}


// ----------------------
// 音声アンロック
// (ブラウザの自動再生制限のため、最初のクリックで音を有効化する。
//  成功するまで案内バナーを表示し続ける)
// ----------------------
function tryUnlockAudio() {

    alarm.currentTime = 0;

    alarm.play().then(() => {

        alarm.pause();
        alarm.currentTime = 0;

        audioNotice.style.display = "none";

        document.body.removeEventListener("click", tryUnlockAudio);

    }).catch(() => {});

}

document.body.addEventListener("click", tryUnlockAudio);


// ----------------------
// 設定保存・監視切替の確認
// ----------------------
document.querySelector("form").addEventListener("submit", (e) => {

    // すでに監視中なら、切り替えてよいか確認する
    if (lastStatus && lastStatus.running && lastStatus.config) {

        const c = lastStatus.config;

        const ok = confirm(
            `現在 ${c.line} ${c.station} を監視中です。\n` +
            "停止して新しい監視に切り替えますか?"
        );

        if (!ok) {
            e.preventDefault();
            trainInput.value = "";  // キャンセル時は列車選択を破棄
            return;
        }

    }

    localStorage.setItem("line", lineSelect.value);
    localStorage.setItem("station", stationSelect.value);
    localStorage.setItem("destination", destinationSelect.value);

});


// ----------------------
// 監視状態の表示更新
// ----------------------
function setStatusView(state, text) {

    const lamp = document.getElementById("statusLamp");
    const statusText = document.getElementById("statusText");

    const classes = {
        alarm: "lamp alarm",
        online: "lamp online",
        offline: "lamp offline",
    };

    lamp.className = classes[state] || classes.offline;
    statusText.textContent = text;

}


// 監視条件テーブルの「路線」セルにカラードット付きで表示する
function setLineCell(cell, config) {

    cell.textContent = "";

    if (!config) {
        cell.textContent = "-";
        return;
    }

    const dot = document.createElement("span");
    dot.className = "lineDot";
    dot.style.background = config.color || "#999";

    cell.appendChild(dot);
    cell.appendChild(document.createTextNode(config.line));

}


async function checkAlarm() {

    try {

        const res = await fetch("/status");
        const data = await res.json();

        lastStatus = data;

        // 監視条件
        const cfg = data.config;

        setLineCell(document.getElementById("cfgLine"), cfg);

        document.getElementById("cfgStation").textContent =
            cfg ? cfg.station : "-";

        document.getElementById("cfgDestination").textContent =
            cfg ? (cfg.destination || "指定なし") : "-";

        document.getElementById("cfgTrain").textContent =
            cfg ? (cfg.train || "指定なし") : "-";

        // 検知状況
        document.getElementById("lastCheck").textContent =
            data.last_check || "-";

        document.getElementById("lastTrain").textContent =
            data.train
                ? `${data.line} ${data.station} → ` +
                  `${data.destination || "-"} (${data.train})`
                : "-";

        if (!data.running && !data.active) {

            setStatusView("offline", "停止中");
            document.getElementById("monitorState").textContent = "停止中";

        } else if (data.active) {

            setStatusView("alarm", "通知中");
            document.getElementById("monitorState").textContent = "🚨 通知中";

        } else {

            setStatusView("online", "監視中");
            document.getElementById("monitorState").textContent = "🟢 監視中";

        }

        if (data.active && !alarmPlaying) {

            alarmPlaying = true;

            lineText.textContent = "🚇 " + (data.line || "");

            stationText.textContent =
                "🚉 " + data.station + " → " + (data.destination || "-");

            trainText.textContent =
                "🚆 列番 : " + data.train;

            alarmScreen.style.display = "flex";

            alarm.pause();
            alarm.currentTime = 0;

            alarm.play().catch(err => {
                console.log("Alarm play failed:", err);
            });

        }

    } catch (e) {

        // サーバーに繋がらない状態を停止中と区別して表示する
        lastStatus = null;
        setStatusView("offline", "サーバー未接続");

        console.log(e);

    }

}


// ----------------------
// 監視対象列車の現在位置(路線図表示)
// ----------------------
function el(tag, className, text) {

    const e = document.createElement(tag);

    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;

    return e;

}


function arrivalText(t, station) {

    // 「木場まで: あと3駅(約6分)」のような到着情報を組み立てる
    if (t.remaining === 0) {
        return `${station} に到着`;
    }

    if (t.approaching && t.remaining !== null) {
        const eta = t.eta_minutes !== null ? `(約${t.eta_minutes}分)` : "";
        return `${station}まで: あと${t.remaining}駅${eta}`;
    }

    if (t.approaching === false) {
        return `${station}とは逆方向`;
    }

    return "進行方向を判定できません";

}


// 1本の列車の路線図(駅の並び+列車アイコン)を作る
function buildRouteMap(line, targetStation, t) {

    // 進行方向が常に「左→右」になるよう描画順を決める
    const order = t.direction === -1
        ? [...line.stations].reverse()
        : [...line.stations];

    const known = t.now_stations || [];
    const moving = known.length === 2;

    // 描画順での列車位置(駅上: 整数 / 駅間: +0.5)
    let trainPos = null;
    if (moving) {
        trainPos = Math.min(
            order.indexOf(known[0]), order.indexOf(known[1])
        ) + 0.5;
    } else if (known.length === 1) {
        trainPos = order.indexOf(known[0]);
    }

    const map = el("div", "routeMap");

    // ヘッダ: 列番・種別・行先と方面
    const header = el(
        "div", "routeHeader",
        `🚆 ${t.number} ${t.type} ${t.destination}行` +
        (t.delay ? ` / ${t.delay}` : "")
    );
    if (t.direction !== 0) {
        header.appendChild(
            el("span", "routeDirection", `${order[order.length - 1]}方面 →`)
        );
    }
    map.appendChild(header);

    // 路線図本体
    const scroll = el("div", "routeScroll");
    const row = el("div", "routeLine");
    const colored = t.direction !== 0 && trainPos !== null;

    order.forEach((name, i) => {

        // 駅間の線(1駅目以降の手前に挟む)
        if (i > 0) {
            const seg = el("div", "routeSeg");
            if (colored && trainPos >= i) seg.classList.add("passed");
            if (moving && trainPos === i - 0.5) {
                seg.appendChild(el("span", "trainIcon", "🚆"));
            }
            row.appendChild(seg);
        }

        const st = el("div", "routeStation");

        if (name === targetStation) st.classList.add("target");
        if (colored) {
            if (i < trainPos) st.classList.add("passed");
            if (i > trainPos) st.classList.add("upcoming");
        }

        const marker = el("div", "marker");
        if (!moving && trainPos === i) {
            st.classList.add("current");
            marker.appendChild(el("span", "trainIcon", "🚆"));
        } else {
            marker.appendChild(el("div", "dot"));
        }

        st.appendChild(marker);
        st.appendChild(el("div", "name", name));
        row.appendChild(st);

    });

    scroll.appendChild(row);
    map.appendChild(scroll);

    // 情報行: 現在駅・次駅・監視駅まで・終点まで
    const state = moving ? "(走行中)" : (known.length ? "(停車中)" : "");
    map.appendChild(el(
        "div", "routeInfo",
        `現在: ${t.position}${state}` +
        (t.next_station ? ` / 次駅: ${t.next_station}` : "")
    ));

    let line2 = arrivalText(t, targetStation);
    if (t.end_station) {
        line2 += ` / 終点(${t.end_station})まで: ` +
            (t.end_remaining === 0 ? "到着" : `あと${t.end_remaining}駅`);
    }
    map.appendChild(el("div", "routeArrival", line2));

    return map;

}


async function updateTracking() {

    try {

        const res = await fetch("/track");

        if (!res.ok) throw new Error("HTTP " + res.status);

        const data = await res.json();

        if (!data.monitoring) {
            trackingArea.textContent = "監視を開始すると表示されます";
            return;
        }

        if (data.trains.length === 0) {
            trackingArea.textContent = "接近中の対象列車はありません";
            return;
        }

        const line = lines.find(l => l.id === data.line_id);

        if (!line) return;  // 路線マスタ読み込み前は次回更新に任せる

        trackingArea.innerHTML = "";

        data.trains.forEach(t => {
            trackingArea.appendChild(buildRouteMap(line, data.station, t));
        });

        // 列車アイコンが見える位置へ自動スクロール
        trackingArea.querySelectorAll(".routeScroll").forEach(sc => {
            const icon = sc.querySelector(".trainIcon");
            if (icon) {
                const iconRect = icon.getBoundingClientRect();
                const scRect = sc.getBoundingClientRect();
                sc.scrollLeft +=
                    iconRect.left - scRect.left - sc.clientWidth / 2;
            }
        });

    } catch (e) {

        console.log("位置情報の取得に失敗:", e);
        trackingArea.textContent = "位置情報を取得できませんでした";

    }

}


// ----------------------
// 履歴・最終検知の更新
// ----------------------
async function loadHistory() {

    try {

        const res = await fetch("/history");
        const list = await res.json();

        const body = document.getElementById("historyBody");
        body.innerHTML = "";

        list.forEach(item => {

            const tr = document.createElement("tr");

            [item.time, item.line, item.station,
             item.destination, item.train].forEach(value => {

                const td = document.createElement("td");
                td.textContent = value || "-";
                tr.appendChild(td);

            });

            body.appendChild(tr);

        });

        document.getElementById("lastDetect").textContent =
            list.length > 0 ? list[0].time : "-";

    } catch (e) {

        console.log(e);

    }

}


// ----------------------
// 統計取得
// ----------------------
async function loadStats() {

    try {

        const res = await fetch("/stats");
        const stats = await res.json();

        document.getElementById("todayCount").textContent = stats.today;
        document.getElementById("totalCount").textContent = stats.total;

    } catch (e) {

        console.log(e);

    }

}


// ----------------------
// 通知確認
// ----------------------
function acknowledge() {

    fetch("/ack", {
        method: "POST"
    }).catch(e => console.log(e));

    alarm.pause();
    alarm.currentTime = 0;

    alarmScreen.style.display = "none";

    alarmPlaying = false;

    checkAlarm();

}


// ----------------------
// テスト通知
// ----------------------
function testAlarm() {

    // Safari用に一度再生して音声を有効化
    tryUnlockAudio();

    fetch("/test", {
        method: "POST"
    }).catch(e => console.log(e));

}


// ----------------------
// 監視停止
// ----------------------
async function stopMonitor() {

    try {

        const res = await fetch("/stop", {
            method: "POST"
        });

        if (!res.ok) {
            alert("停止に失敗しました");
            return;
        }

        alarm.pause();
        alarm.currentTime = 0;

        alarmPlaying = false;

        alarmScreen.style.display = "none";

        checkAlarm();

    } catch (e) {

        console.log(e);

        alert("停止できませんでした");

    }

}


// ----------------------
// 定期更新
// ----------------------
setInterval(checkAlarm, 1000);
setInterval(loadHistory, 3000);
setInterval(loadStats, 5000);
setInterval(loadTrains, 10000);
setInterval(updateTracking, 5000);


// 初回実行
checkAlarm();
loadHistory();
loadStats();
updateTracking();
