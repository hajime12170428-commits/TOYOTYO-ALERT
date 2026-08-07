# monitor.py のテスト(判定ロジック・CSV・スレッド管理・利用者分離)
import threading
import time

import monitor as monitor_mod
from monitor import MonitorManager, TrainMonitor, match_trains

LINE = {
    "id": "Tozai",
    "api_id": "TokyoMetro_Tozai",
    "name": "東西線",
    "color": "#009BBF",
    "stations": ["木場"],
    "destinations": ["西船橋"],
}


def make_train(number="A1234S", destination="西船橋", now=("木場",)):
    return {"number": number, "destination": destination, "now": list(now)}


# ----------------------
# match_trains(判定ロジック)
# ----------------------

class TestMatchTrains:

    def test_station_match(self):
        trains = [make_train(now=["木場"]), make_train("B999S", now=["東陽町"])]
        matched = match_trains(trains, "木場", "", "")
        assert [t["number"] for t in matched] == ["A1234S"]

    def test_station_between(self):
        # 駅間走行中は now が2駅になる
        trains = [make_train(now=["木場", "東陽町"])]
        assert len(match_trains(trains, "木場", "", "")) == 1
        assert len(match_trains(trains, "東陽町", "", "")) == 1

    def test_destination_filter(self):
        trains = [make_train(destination="西船橋"), make_train("B1", destination="中野")]
        matched = match_trains(trains, "木場", "西船橋", "")
        assert [t["number"] for t in matched] == ["A1234S"]

    def test_empty_destination_matches_all(self):
        trains = [make_train(destination="西船橋"), make_train("B1", destination="中野")]
        assert len(match_trains(trains, "木場", "", "")) == 2

    def test_train_number_filter(self):
        trains = [make_train("A1234S"), make_train("B5678S")]
        matched = match_trains(trains, "木場", "", "B5678S")
        assert [t["number"] for t in matched] == ["B5678S"]

    def test_no_match(self):
        assert match_trains([make_train(now=["中野"])], "木場", "", "") == []

    def test_malformed_train_entries(self):
        # API がフィールド欠落したデータを返しても落ちない
        trains = [{}, {"number": "X"}, {"now": []}]
        assert match_trains(trains, "木場", "", "") == []


# ----------------------
# テスト用のAPIモック
# ----------------------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """呼び出しごとに payloads を順に返す(最後は繰り返し)"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0

    def get(self, url, timeout=None):
        payload = self._payloads[min(self.calls, len(self._payloads) - 1)]
        self.calls += 1
        return FakeResponse(payload)

    def close(self):
        pass


def new_alarm_data():
    return {
        "active": False,
        "line": "",
        "station": "",
        "destination": "",
        "train": "",
    }


def wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def use_fake_api(monkeypatch, payloads):
    session = FakeSession(payloads)
    monkeypatch.setattr(monitor_mod.requests, "Session", lambda: session)
    monkeypatch.setattr(monitor_mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(monitor_mod, "ERROR_INTERVAL", 0.02)
    monkeypatch.setattr(monitor_mod, "CACHE_TTL", 0.0)  # キャッシュ無効化
    monkeypatch.setattr(monitor_mod, "_line_cache", {})
    return session


# ----------------------
# TrainMonitor(スレッド管理・通知)
# ----------------------

class TestTrainMonitor:

    def test_detects_and_notifies(self, monkeypatch):
        use_fake_api(monkeypatch, [
            {"running": [], "noRunning": [make_train()]},
        ])
        alarm_data = new_alarm_data()
        notes = []
        m = TrainMonitor()

        m.start(LINE, "木場", "", "", alarm_data, on_notify=notes.append)
        try:
            assert wait_until(lambda: alarm_data["active"])
            assert alarm_data["train"] == "A1234S"
            assert alarm_data["line"] == "東西線"
            # on_notify に履歴エントリが渡る
            assert wait_until(lambda: len(notes) == 1)
            assert notes[0]["station"] == "木場"
            assert notes[0]["train"] == "A1234S"
        finally:
            m.stop()

    def test_no_duplicate_notification(self, monkeypatch):
        # 同じ列車が居続けても通知は1回だけ
        session = use_fake_api(monkeypatch, [
            {"running": [], "noRunning": [make_train()]},
        ])
        notes = []
        m = TrainMonitor()

        m.start(LINE, "木場", "", "", new_alarm_data(), on_notify=notes.append)
        try:
            assert wait_until(lambda: session.calls >= 5)
            assert len(notes) == 1
        finally:
            m.stop()

    def test_renotify_after_leaving(self, monkeypatch):
        # 一度離れて戻ってきた列車は再通知される
        present = {"running": [], "noRunning": [make_train()]}
        absent = {"running": [], "noRunning": []}
        use_fake_api(monkeypatch, [present, absent, present])
        notes = []
        m = TrainMonitor()

        m.start(LINE, "木場", "", "", new_alarm_data(), on_notify=notes.append)
        try:
            assert wait_until(lambda: len(notes) >= 2)
        finally:
            m.stop()

    def test_stop_terminates_thread(self, monkeypatch):
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        m = TrainMonitor()
        before = threading.active_count()

        m.start(LINE, "木場", "", "", new_alarm_data())
        assert wait_until(lambda: m.is_running)

        m.stop()
        assert not m.is_running
        assert wait_until(lambda: threading.active_count() <= before)

    def test_restart_does_not_leak_threads(self, monkeypatch):
        """再開始で古いスレッドが生き残らないこと"""
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        m = TrainMonitor()
        before = threading.active_count()

        for _ in range(5):
            m.start(LINE, "木場", "", "", new_alarm_data())

        assert wait_until(
            lambda: threading.active_count() <= before + 1
        ), "監視スレッドが多重起動している"

        m.stop()
        assert wait_until(lambda: threading.active_count() <= before)

    def test_api_error_keeps_running(self, monkeypatch):
        class ErrorSession:
            def __init__(self):
                self.calls = 0

            def get(self, url, timeout=None):
                self.calls += 1
                raise monitor_mod.requests.ConnectionError("down")

            def close(self):
                pass

        session = ErrorSession()
        monkeypatch.setattr(monitor_mod.requests, "Session", lambda: session)
        monkeypatch.setattr(monitor_mod, "POLL_INTERVAL", 0.02)
        monkeypatch.setattr(monitor_mod, "ERROR_INTERVAL", 0.02)
        monkeypatch.setattr(monitor_mod, "CACHE_TTL", 0.0)
        monkeypatch.setattr(monitor_mod, "_line_cache", {})

        m = TrainMonitor()
        m.start(LINE, "木場", "", "", new_alarm_data())
        try:
            # エラーが起きても監視ループは継続する
            assert wait_until(lambda: session.calls >= 3)
            assert m.is_running
        finally:
            m.stop()

    def test_unexpected_data_keeps_running(self, monkeypatch):
        """APIが想定外の形のデータを返しても監視スレッドが死なないこと"""
        bad_payload = {
            "running": [],
            # now が null → 判定時に TypeError が発生するデータ
            "noRunning": [{"number": "X1", "destination": "西船橋", "now": None}],
        }
        session = use_fake_api(monkeypatch, [bad_payload])
        m = TrainMonitor()

        m.start(LINE, "木場", "", "", new_alarm_data())
        try:
            assert wait_until(lambda: session.calls >= 3)
            assert m.is_running, "想定外データで監視スレッドが停止した"
        finally:
            m.stop()

    def test_config_and_last_check_lifecycle(self, monkeypatch):
        """監視条件と最終確認時刻が稼働中のみ公開されること"""
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        m = TrainMonitor()

        assert m.config is None
        assert m.last_check is None

        m.start(LINE, "木場", "西船橋", "A1", new_alarm_data())
        try:
            assert wait_until(lambda: m.last_check is not None)

            cfg = m.config
            assert cfg["line"] == "東西線"
            assert cfg["station"] == "木場"
            assert cfg["destination"] == "西船橋"
            assert cfg["color"] == "#009BBF"
        finally:
            m.stop()

        assert m.config is None
        assert m.last_check is None

    def test_auto_expiry(self, monkeypatch):
        """連続監視の上限を超えたら自動終了し on_expire が呼ばれること"""
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        monkeypatch.setattr(monitor_mod, "MAX_RUN_SECONDS", 0.05)

        expired = []
        m = TrainMonitor()

        m.start(LINE, "木場", "", "", new_alarm_data(),
                on_expire=lambda: expired.append(1))

        assert wait_until(lambda: expired)
        assert wait_until(lambda: not m.is_running)


# ----------------------
# MonitorManager(利用者分離)
# ----------------------

class TestMonitorManager:

    def test_users_run_independently(self, monkeypatch):
        # userA(木場)だけ検知し、userB(東陽町)には通知されない
        use_fake_api(monkeypatch, [
            {"running": [], "noRunning": [make_train(now=["木場"])]},
        ])
        mgr = MonitorManager()
        state_a = new_alarm_data()
        state_b = new_alarm_data()

        assert mgr.start("userA", LINE, "木場", "", "", state_a)
        assert mgr.start("userB", LINE, "東陽町", "", "", state_b)
        try:
            assert wait_until(lambda: state_a["active"])
            assert not state_b["active"]

            # userA を止めても userB は動き続ける
            mgr.stop("userA")
            monitor_b = mgr.get("userB")
            assert monitor_b is not None and monitor_b.is_running
        finally:
            mgr.stop("userA")
            mgr.stop("userB")

    def test_restart_replaces_own_monitor_only(self, monkeypatch):
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        mgr = MonitorManager()

        mgr.start("userA", LINE, "木場", "", "", new_alarm_data())
        mgr.start("userB", LINE, "東陽町", "", "", new_alarm_data())
        mgr.start("userA", LINE, "浦安", "", "", new_alarm_data())
        try:
            assert mgr.get("userA").config["station"] == "浦安"
            assert mgr.get("userB").config["station"] == "東陽町"
        finally:
            mgr.stop("userA")
            mgr.stop("userB")

    def test_capacity_limit(self, monkeypatch):
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        mgr = MonitorManager(max_monitors=1)

        assert mgr.start("userA", LINE, "木場", "", "", new_alarm_data())
        assert wait_until(lambda: mgr.get("userA").is_running)

        # 上限到達 → 別利用者は開始できない
        assert not mgr.start("userB", LINE, "木場", "", "", new_alarm_data())

        # 同一利用者の切り替えは枠を消費しないので可能
        assert mgr.start("userA", LINE, "浦安", "", "", new_alarm_data())

        # 停止すれば枠が空く
        mgr.stop("userA")
        assert mgr.start("userB", LINE, "木場", "", "", new_alarm_data())
        mgr.stop("userB")

    def test_stopped_monitors_are_pruned(self, monkeypatch):
        use_fake_api(monkeypatch, [{"running": [], "noRunning": []}])
        mgr = MonitorManager()

        mgr.start("userA", LINE, "木場", "", "", new_alarm_data())
        mgr.stop("userA")

        # 次の start 時に停止済みエントリが掃除される
        mgr.start("userB", LINE, "木場", "", "", new_alarm_data())
        try:
            assert mgr.get("userA") is None
        finally:
            mgr.stop("userB")


# ----------------------
# APIキャッシュ(利用者間で共有)
# ----------------------

class TestLineCache:

    def test_cache_shares_response(self, monkeypatch):
        session = FakeSession([{"running": [], "noRunning": []}])
        monkeypatch.setattr(monitor_mod, "_line_cache", {})
        monkeypatch.setattr(monitor_mod, "CACHE_TTL", 60.0)

        d1 = monitor_mod.fetch_line_data(session, "TokyoMetro_Tozai")
        d2 = monitor_mod.fetch_line_data(session, "TokyoMetro_Tozai")

        assert d1 is d2
        assert session.calls == 1  # 2回目はキャッシュから

    def test_cache_separated_by_line(self, monkeypatch):
        session = FakeSession([{"running": [], "noRunning": []}])
        monkeypatch.setattr(monitor_mod, "_line_cache", {})
        monkeypatch.setattr(monitor_mod, "CACHE_TTL", 60.0)

        monitor_mod.fetch_line_data(session, "TokyoMetro_Tozai")
        monitor_mod.fetch_line_data(session, "TokyoMetro_Ginza")

        assert session.calls == 2  # 路線が違えば別々に取得
