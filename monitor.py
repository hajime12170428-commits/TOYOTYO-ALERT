# 列車接近監視
#
# TrainMonitor が 1 本の監視スレッドを管理し、MonitorManager が
# 「利用者ID → TrainMonitor」を管理する(利用者ごとに完全に独立)。
#
# - start() のたびに前のスレッドを threading.Event で確実に止める
# - 同じ路線のAPI応答は利用者間でキャッシュ共有し、利用者数が
#   増えてもAPIへのアクセスは路線あたり最大 1回/CACHE_TTL 秒に抑える
# - 履歴の保存先(DB等)は on_notify コールバックで注入する

import csv
import logging
import os
import threading
import time

import requests

from timeutil import now_str

logger = logging.getLogger(__name__)

API_BASE = "https://nkth.info/traffic_info/ODPT/now"
REQUEST_TIMEOUT = 10   # APIリクエストのタイムアウト(秒)
POLL_INTERVAL = 2      # 通常時のポーリング間隔(秒)
ERROR_INTERVAL = 10    # 通信エラー後の待機(秒) - 障害時にAPIを叩き続けない
CACHE_TTL = 1.5        # 路線APIキャッシュの有効期間(秒)

# サーバー保護: 全体の同時監視数の上限
MAX_MONITORS = int(os.environ.get("MAX_MONITORS", "50"))
# 放置対策: 連続監視の上限(超えると自動終了して on_expire を呼ぶ)
MAX_RUN_SECONDS = int(os.environ.get("MAX_MONITOR_HOURS", "12")) * 3600

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_CSV = os.path.join(BASE_DIR, "history.csv")
CSV_HEADER = ["日時", "路線", "駅", "行先", "列番"]

# 利用者ごとのアラーム状態辞書を守るロック(app.py と共有)
state_lock = threading.Lock()

# 路線ごとのAPI応答キャッシュ { api_id: (取得時刻, データ) }
_cache_lock = threading.Lock()
_line_cache = {}


def fetch_line_data(session, api_id):
    """路線の走行情報を取得する。CACHE_TTL 以内は利用者間で共有する。"""
    now = time.time()

    with _cache_lock:
        cached = _line_cache.get(api_id)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    response = session.get(
        f"{API_BASE}?line={api_id}", timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()

    with _cache_lock:
        _line_cache[api_id] = (time.time(), data)

    return data


def save_csv(line_name, station, destination, train, path=None):
    """通知1件を運用ログCSVに追記する(全利用者共通のサーバー側ログ)。"""
    path = path or HISTORY_CSV
    new_file = not os.path.exists(path)

    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(CSV_HEADER)
            writer.writerow([now_str(), line_name, station, destination, train])
    except OSError as e:
        # Excel で開いたままなどで書けないことがある
        logger.error("履歴CSVの保存に失敗しました: %s", e)


def match_trains(trains, station, destination, train_no):
    """監視条件(駅・行先・列番)に合致する列車を返す。空の条件は無視。"""
    matched = []
    for t in trains:
        if destination and t.get("destination") != destination:
            continue
        if train_no and t.get("number") != train_no:
            continue
        if station not in t.get("now", []):
            continue
        matched.append(t)
    return matched


class TrainMonitor:
    """1利用者分の監視スレッドを管理する。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._config = None     # 現在の監視条件(UI表示用)
        self._last_poll = None  # 最後にAPI確認に成功した時刻(epoch秒)

    def start(self, line, station, destination, train_no, alarm_data,
              on_notify=None, on_expire=None):
        """監視を開始する。既存の監視は先に停止させる。

        on_notify(entry): 検知のたびに呼ばれる(履歴の永続化用)
        on_expire():      監視時間の上限で自動終了したときに呼ばれる
        """
        with self._lock:
            self._stop_locked()

            self._config = {
                "line_id": line["id"],
                "line": line["name"],
                "color": line["color"],
                "station": station,
                "destination": destination,
                "train": train_no,
            }

            stop_event = threading.Event()
            self._stop_event = stop_event
            self._thread = threading.Thread(
                target=self._run,
                args=(stop_event, line, station, destination, train_no,
                      alarm_data, on_notify, on_expire),
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            # 待機は Event で即座に抜ける。通信中の場合のみ少し待つ。
            thread.join(timeout=0.5)
        self._thread = None
        self._config = None
        self._last_poll = None

    @property
    def is_running(self):
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    @property
    def config(self):
        """現在の監視条件。停止中は None。"""
        return self._config if self.is_running else None

    @property
    def last_check(self):
        """最後にAPI確認に成功した時刻(epoch秒)。停止中は None。"""
        return self._last_poll if self.is_running else None

    def _run(self, stop_event, line, station, destination, train_no,
             alarm_data, on_notify, on_expire):
        notified = set()  # 通知済み列番(このスレッド専用)
        session = requests.Session()
        started_at = time.time()

        logger.info(
            "監視開始: %s %s 行先=%s 列番=%s",
            line["name"], station, destination or "指定なし", train_no or "指定なし",
        )

        while not stop_event.is_set():

            # 放置された監視を自動終了する
            if MAX_RUN_SECONDS and time.time() - started_at > MAX_RUN_SECONDS:
                logger.info(
                    "監視を自動終了(連続監視の上限超過): %s %s",
                    line["name"], station,
                )
                if on_expire and not stop_event.is_set():
                    try:
                        on_expire()
                    except Exception:
                        logger.exception("自動終了処理でエラー")
                break

            interval = POLL_INTERVAL
            try:
                data = fetch_line_data(session, line["api_id"])

                if not stop_event.is_set():
                    self._last_poll = time.time()

                trains = data.get("running", []) + data.get("noRunning", [])
                matched = match_trains(trains, station, destination, train_no)
                current = {t.get("number", "") for t in matched}

                for t in matched:
                    number = t.get("number", "")
                    if number in notified:
                        continue  # 同じ列車は駅を離れるまで再通知しない
                    notified.add(number)
                    if stop_event.is_set():
                        break
                    self._notify(line, station, t, alarm_data, on_notify)

                # 駅から離れた列車は再通知できるようにする
                notified &= current

            except (requests.RequestException, ValueError) as e:
                logger.warning("監視エラー(%s): %s", line["name"], e)
                interval = ERROR_INTERVAL
            except Exception:
                # APIが想定外のデータを返しても監視は止めない(接近見逃し防止)
                logger.exception("監視ループで想定外のエラー(%s)", line["name"])
                interval = ERROR_INTERVAL

            stop_event.wait(interval)

        session.close()
        logger.info("監視終了: %s %s", line["name"], station)

    @staticmethod
    def _notify(line, station, train, alarm_data, on_notify):
        number = train.get("number", "")
        destination = train.get("destination", "")

        logger.info(
            "接近検知: %s %s 行先=%s 列番=%s",
            line["name"], station, destination, number,
        )

        entry = {
            "time": now_str(),
            "line": line["name"],
            "station": station,
            "destination": destination,
            "train": number,
        }

        with state_lock:
            alarm_data["active"] = True
            alarm_data["line"] = line["name"]
            alarm_data["station"] = station
            alarm_data["destination"] = destination
            alarm_data["train"] = number

        if on_notify:
            try:
                on_notify(entry)
            except Exception:
                logger.exception("履歴の保存に失敗")

        save_csv(line["name"], station, destination, number)


class MonitorManager:
    """利用者ID → TrainMonitor の対応を管理する。"""

    def __init__(self, max_monitors=None):
        self._lock = threading.Lock()
        self._monitors = {}
        self.max_monitors = max_monitors or MAX_MONITORS

    def start(self, user_id, line, station, destination, train_no,
              alarm_data, on_notify=None, on_expire=None):
        """利用者の監視を開始する。上限超過なら False を返す。"""
        with self._lock:
            self._prune_locked()

            existing = self._monitors.get(user_id)

            # 新規に枠を消費する場合のみ上限を確認する
            if existing is None or not existing.is_running:
                running = sum(
                    1 for m in self._monitors.values() if m.is_running
                )
                if running >= self.max_monitors:
                    logger.warning(
                        "監視数が上限(%d)のため開始できません: user=%s",
                        self.max_monitors, user_id[:8],
                    )
                    return False

            if existing is None:
                existing = TrainMonitor()
                self._monitors[user_id] = existing

        existing.start(line, station, destination, train_no, alarm_data,
                       on_notify=on_notify, on_expire=on_expire)
        return True

    def stop(self, user_id):
        with self._lock:
            monitor = self._monitors.get(user_id)
        if monitor:
            monitor.stop()

    def get(self, user_id):
        """利用者の TrainMonitor(なければ None)。"""
        with self._lock:
            return self._monitors.get(user_id)

    def _prune_locked(self):
        """停止済みの監視をテーブルから取り除く(メモリ増加防止)。"""
        dead = [
            uid for uid, m in self._monitors.items() if not m.is_running
        ]
        for uid in dead:
            del self._monitors[uid]


# アプリ全体で共有する監視マネージャ
manager = MonitorManager()
