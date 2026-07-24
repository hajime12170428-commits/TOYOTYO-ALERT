const alarmScreen = document.getElementById("alarmScreen");
const alarm = document.getElementById("alarm");

const stationText = document.getElementById("stationText");
const trainText = document.getElementById("trainText");

let alarmPlaying = false;


// ----------------------
// 前回設定を復元
// ----------------------
window.addEventListener("load", () => {

    const station = localStorage.getItem("station");
    const destination = localStorage.getItem("destination");
    const train = localStorage.getItem("train");

    if (station)
        document.querySelector("select[name='station']").value = station;

    if (destination)
        document.querySelector("select[name='destination']").value = destination;

    if (train)
        document.querySelector("input[name='train']").value = train;

});


// ----------------------
// Safari音声解除
// ----------------------
document.body.addEventListener("click", () => {

    alarm.currentTime = 0;

    alarm.play().then(() => {

        alarm.pause();
        alarm.currentTime = 0;

    }).catch(() => {});

}, { once: true });


// ----------------------
// 設定保存
// ----------------------
document.querySelector("form").addEventListener("submit", () => {

    localStorage.setItem(
        "station",
        document.querySelector("select[name='station']").value
    );

    localStorage.setItem(
        "destination",
        document.querySelector("select[name='destination']").value
    );

    localStorage.setItem(
        "train",
        document.querySelector("input[name='train']").value
    );

});


// ----------------------
// アラーム確認
// ----------------------
async function checkAlarm() {

    try {

        const res = await fetch("/status");
        const data = await res.json();

        const lamp = document.getElementById("statusLamp");
        const text = document.getElementById("statusText");

        lamp.className = "lamp online";
        text.innerHTML = "監視中";

        document.getElementById("monitorState").innerHTML =
            data.active ? "🚨 通知中" : "🟢 監視中";

        document.getElementById("monitorStation").innerHTML =
            data.station || "-";

        document.getElementById("monitorDestination").innerHTML =
            data.destination || "-";

        document.getElementById("monitorTrain").innerHTML =
            data.train || "-";

        if (data.active && !alarmPlaying) {

            alarmPlaying = true;

            lamp.className = "lamp alarm";
            text.innerHTML = "通知中";

            stationText.innerHTML =
                "🚉 " + data.station + " → " + data.destination;

            trainText.innerHTML =
                "🚆 列番 : " + data.train;

            alarmScreen.style.display = "flex";

            alarm.pause();
            alarm.currentTime = 0;

            alarm.play().catch(err => {
                console.log("Alarm play failed:", err);
            });

        }

    } catch (e) {

        console.log(e);

    }

}
// ----------------------
// 履歴取得
// ----------------------
async function loadHistory() {

    try {

        const res = await fetch("/history");
        const list = await res.json();

        let html = "";

        list.forEach(item => {

            html += `
                <tr>
                    <td>${item.time}</td>
                    <td>${item.station}</td>
                    <td>${item.destination}</td>
                    <td>${item.train}</td>
                </tr>
            `;

        });

        document.getElementById("historyBody").innerHTML = html;

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

        document.getElementById("todayCount").innerHTML =
            stats.today;

        document.getElementById("totalCount").innerHTML =
            stats.total;

    } catch (e) {

        console.log(e);

    }

}


// ----------------------
// 最終検知時刻更新
// ----------------------
async function updateLastDetect() {

    try {

        const res = await fetch("/history");
        const history = await res.json();

        if (history.length > 0) {

            document.getElementById("lastDetect").innerHTML =
                history[0].time;

        } else {

            document.getElementById("lastDetect").innerHTML =
                "-";

        }

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
    });

    alarm.pause();
    alarm.currentTime = 0;

    alarmScreen.style.display = "none";

    alarmPlaying = false;

    document.getElementById("statusLamp").className = "lamp online";
    document.getElementById("statusText").innerHTML = "監視中";

}


// ----------------------
// テスト通知
// ----------------------
function testAlarm() {

    // Safari用に一度再生して音声を有効化
    alarm.currentTime = 0;

    alarm.play().then(() => {

        alarm.pause();
        alarm.currentTime = 0;

    }).catch(() => {});

    fetch("/test", {
        method: "POST"
    });

}


// ----------------------
// 定期更新
// ----------------------
setInterval(checkAlarm, 1000);
setInterval(loadHistory, 2000);
setInterval(loadStats, 2000);
setInterval(updateLastDetect, 2000);


// 初回実行
checkAlarm();
loadHistory();
loadStats();
updateLastDetect();
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

        document.getElementById("statusLamp").className = "lamp offline";
        document.getElementById("statusText").innerHTML = "停止中";

        document.getElementById("monitorState").innerHTML = "停止中";
        document.getElementById("monitorStation").innerHTML = "-";
        document.getElementById("monitorDestination").innerHTML = "-";
        document.getElementById("monitorTrain").innerHTML = "-";

    } catch (e) {

        console.log(e);

        alert("停止できませんでした");

    }

}