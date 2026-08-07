import logging
import os
import re
import threading
import uuid
from datetime import datetime

from flask import Flask, g, jsonify, render_template, request

import requests

import db
from lines import LINES, get_line
from monitor import fetch_line_data, manager, state_lock
from timeutil import JST, now_str
from tracking import select_tracked

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TRAIN_NO_RE = re.compile(r"^[0-9A-Za-z]{0,10}$")

# Cookie名は旧サービス名(TOYOCHO ALERT)由来だが、変更すると既存利用者の
# 識別が切れるため互換性のために維持している
COOKIE_NAME = "toyotyo_uid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 730  # 2年

db.init_db()

# 利用者ごとのアラーム状態(プロセス内。履歴・統計はSQLite)
_user_states = {}
_states_lock = threading.Lock()

# サーバー再起動時の監視復元(初回リクエストで1度だけ)
_resume_lock = threading.Lock()
_resumed = False


def _blank_state():
    return {
        "active": False,
        "line": "",
        "station": "",
        "destination": "",
        "train": "",
    }


def get_user_state(user_id):
    with _states_lock:
        state = _user_states.get(user_id)
        if state is None:
            state = _blank_state()
            _user_states[user_id] = state
        return state


def _history_writer(user_id):
    def write(entry):
        db.add_history(user_id, entry)
    return write


def _expire_handler(user_id):
    def expire():
        db.deactivate_monitor(user_id)
    return expire


def _start_user_monitor(user_id, line, station, destination, train):
    state = get_user_state(user_id)
    return manager.start(
        user_id, line, station, destination, train, state,
        on_notify=_history_writer(user_id),
        on_expire=_expire_handler(user_id),
    )


def _resume_monitors_once():
    """再起動前に動いていた監視をDBから復元する。"""
    global _resumed
    if _resumed:
        return
    with _resume_lock:
        if _resumed:
            return
        _resumed = True

        for row in db.get_active_monitors():
            line = get_line(row["line_id"])
            if line is None or not _start_user_monitor(
                row["user_id"], line,
                row["station"], row["destination"], row["train"],
            ):
                db.deactivate_monitor(row["user_id"])
            else:
                logger.info(
                    "監視を復元: user=%s %s %s",
                    row["user_id"][:8], line["name"], row["station"],
                )


@app.before_request
def identify_user():
    _resume_monitors_once()

    uid = request.cookies.get(COOKIE_NAME, "")
    try:
        uuid.UUID(uid)
        g.new_user = False
    except ValueError:
        uid = str(uuid.uuid4())
        g.new_user = True
        db.ensure_user(uid)

    g.user_id = uid


@app.after_request
def issue_user_cookie(response):
    if getattr(g, "new_user", False):
        response.set_cookie(
            COOKIE_NAME,
            g.user_id,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
@app.route("/healthz")
def health():
    """死活監視用(Renderのヘルスチェック)。"""
    return jsonify({"status": "ok", "lines": len(LINES)})


@app.route("/lines")
def get_lines():
    return jsonify(LINES)


# 在線一覧の取得用(監視スレッドとキャッシュを共有するため追加負荷なし)
_api_session = requests.Session()


@app.route("/trains")
def get_trains():
    """選択路線の現在走行中の列車一覧(列番選択UI用)。"""
    line = get_line(request.args.get("line", ""))
    if line is None:
        return jsonify({"error": "路線が不正です"}), 400

    try:
        data = fetch_line_data(_api_session, line["api_id"])
    except Exception as e:
        logger.warning("在線一覧の取得に失敗(%s): %s", line["name"], e)
        return jsonify({"error": "在線情報を取得できませんでした"}), 502

    trains = data.get("running", []) + data.get("noRunning", [])

    return jsonify([
        {
            "number": t.get("number", ""),
            "destination": t.get("destination", ""),
            "type": t.get("type", ""),
            "now": t.get("now", []),
            "direction": t.get("direction_text", ""),
            "delay": t.get("delay_text", ""),
        }
        for t in trains
        if t.get("number")  # 列番がない列車は選択できないため除外
    ])


def _validate_start_form(form):
    """監視開始フォームを検証し、(line, station, destination, train, error) を返す。"""
    line_id = form.get("line", "").strip()
    station = form.get("station", "").strip()
    destination = form.get("destination", "").strip()
    train = form.get("train", "").strip().upper()

    line = get_line(line_id)
    if line is None:
        return None, None, None, None, "路線を選択してください"
    if station not in line["stations"]:
        return None, None, None, None, f"駅「{station}」は{line['name']}にありません"
    if destination and destination not in line["destinations"]:
        return None, None, None, None, f"行先「{destination}」は{line['name']}では指定できません"
    if not TRAIN_NO_RE.match(train):
        return None, None, None, None, "列番は10文字以内の英数字で入力してください"

    return line, station, destination, train, None


@app.route("/start", methods=["POST"])
def start():
    line, station, destination, train, error = _validate_start_form(request.form)

    if error:
        return render_template("index.html", message=error, error=True)

    user_id = g.user_id
    monitor = manager.get(user_id)
    previous = monitor.config if monitor else None

    # 前回の監視のアラーム状態を引き継がない(履歴は保持)
    manager.stop(user_id)
    state = get_user_state(user_id)
    with state_lock:
        state.update(_blank_state())

    if not _start_user_monitor(user_id, line, station, destination, train):
        return render_template(
            "index.html",
            message="現在利用者が多いため監視を開始できません。しばらくしてからお試しください",
            error=True,
        )

    db.save_monitor(user_id, line["id"], station, destination, train)

    message = f"{line['name']} {station} の監視を開始しました"
    if previous:
        message = (
            f"{previous['line']} {previous['station']} の監視を停止し、"
            + message
        )

    return render_template("index.html", message=message)


@app.route("/stop", methods=["POST"])
def stop():
    manager.stop(g.user_id)
    db.deactivate_monitor(g.user_id)

    state = get_user_state(g.user_id)
    with state_lock:
        state["active"] = False

    return render_template("index.html", message="監視停止しました")


@app.route("/status")
def status():
    monitor = manager.get(g.user_id)
    running = monitor.is_running if monitor else False
    config = monitor.config if monitor else None
    last_check = monitor.last_check if monitor else None

    state = get_user_state(g.user_id)

    with state_lock:
        return jsonify({
            "running": running,
            "config": config,
            "last_check": (
                datetime.fromtimestamp(last_check, JST).strftime("%H:%M:%S")
                if last_check else None
            ),
            "active": state["active"],
            "line": state["line"],
            "station": state["station"],
            "destination": state["destination"],
            "train": state["train"],
        })


@app.route("/track")
def track():
    """監視中の対象列車の現在位置・次駅・残り駅数(表示専用)。"""
    monitor = manager.get(g.user_id)
    config = monitor.config if monitor else None

    if not config:
        return jsonify({"monitoring": False, "trains": []})

    line = get_line(config["line_id"])
    if line is None:
        return jsonify({"monitoring": False, "trains": []})

    try:
        data = fetch_line_data(_api_session, line["api_id"])
    except Exception as e:
        logger.warning("位置情報の取得に失敗(%s): %s", line["name"], e)
        return jsonify({"error": "位置情報を取得できませんでした"}), 502

    trains = data.get("running", []) + data.get("noRunning", [])

    return jsonify({
        "monitoring": True,
        "station": config["station"],
        "line_id": config["line_id"],
        "trains": select_tracked(line, config, trains),
    })


@app.route("/history")
def history():
    return jsonify(db.get_history(g.user_id))


@app.route("/stats")
def get_stats():
    return jsonify(db.get_stats(g.user_id))


@app.route("/ack", methods=["POST"])
def ack():
    state = get_user_state(g.user_id)
    with state_lock:
        state["active"] = False

    return "OK"


@app.route("/test", methods=["POST"])
def test():
    entry = {
        "time": now_str(),
        "line": "テスト",
        "station": "木場",
        "destination": "東陽町",
        "train": "TEST123",
    }

    state = get_user_state(g.user_id)
    with state_lock:
        state["active"] = True
        state["line"] = entry["line"]
        state["station"] = entry["station"]
        state["destination"] = entry["destination"]
        state["train"] = entry["train"]

    db.add_history(g.user_id, entry, is_test=True)

    return "OK"


if __name__ == "__main__":
    # 公開時は debug を無効にする(FLASK_DEBUG=1 で開発モード)
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        port=int(os.environ.get("PORT", "5000")),
    )
