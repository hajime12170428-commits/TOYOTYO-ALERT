# Flask エンドポイントのテスト(利用者分離を含む)
from types import SimpleNamespace

import pytest

import app as app_mod
import db
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # テスト用DBに切り替え
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()

    # 復元処理・共有状態をテストごとに初期化
    monkeypatch.setattr(app_mod, "_resumed", True)
    monkeypatch.setattr(app_mod, "_user_states", {})

    # 実際の監視スレッド・ネットワークは起動しない
    calls = {"start": [], "stop": []}

    def fake_start(user_id, line, station, destination, train_no,
                   alarm_data, **kwargs):
        calls["start"].append((user_id, line, station, destination, train_no))
        return True

    monkeypatch.setattr(app_mod.manager, "start", fake_start)
    monkeypatch.setattr(app_mod.manager, "stop",
                        lambda user_id: calls["stop"].append(user_id))
    monkeypatch.setattr(app_mod.manager, "get", lambda user_id: None)

    app.config["TESTING"] = True

    with app.test_client() as c:
        c.monitor_calls = calls
        yield c


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "監視設定" in res.get_data(as_text=True)


def test_lines_endpoint(client):
    res = client.get("/lines")
    assert res.status_code == 200

    lines = res.get_json()
    assert len(lines) == 10
    assert all("stations" in line and "name" in line for line in lines)


class TestTrainsEndpoint:

    def test_returns_trains_for_line(self, client, monkeypatch):
        monkeypatch.setattr(
            app_mod, "fetch_line_data",
            lambda session, api_id: {
                "running": [],
                "noRunning": [
                    {"number": "A1234S", "destination": "西船橋",
                     "type": "普通", "now": ["木場"],
                     "direction_text": "西船橋方面", "delay_text": ""},
                    {"number": "", "destination": "中野", "now": ["落合"]},
                ],
            },
        )

        res = client.get("/trains?line=Tozai")
        assert res.status_code == 200

        trains = res.get_json()
        assert len(trains) == 1  # 列番なしの列車は除外される
        assert trains[0]["number"] == "A1234S"
        assert trains[0]["destination"] == "西船橋"
        assert trains[0]["now"] == ["木場"]

    def test_unknown_line(self, client):
        assert client.get("/trains?line=Yamanote").status_code == 400
        assert client.get("/trains").status_code == 400

    def test_api_failure(self, client, monkeypatch):
        def boom(session, api_id):
            raise ValueError("api down")

        monkeypatch.setattr(app_mod, "fetch_line_data", boom)

        assert client.get("/trains?line=Tozai").status_code == 502


class TestTrackEndpoint:

    def test_not_monitoring(self, client):
        res = client.get("/track")
        assert res.status_code == 200
        assert res.get_json() == {"monitoring": False, "trains": []}

    def test_monitoring_returns_tracked_trains(self, client, monkeypatch):
        monkeypatch.setattr(
            app_mod.manager, "get",
            lambda user_id: SimpleNamespace(
                config={"line_id": "Tozai", "line": "東西線",
                        "station": "木場", "destination": "", "train": ""},
                is_running=True,
            ),
        )
        monkeypatch.setattr(
            app_mod, "fetch_line_data",
            lambda session, api_id: {
                "running": [],
                "noRunning": [
                    {"number": "A1", "type": "普通", "destination": "西船橋",
                     "now": ["門前仲町", "木場"], "direction_text": "",
                     "delay_text": ""},
                ],
            },
        )

        data = client.get("/track").get_json()
        assert data["monitoring"] is True
        assert data["station"] == "木場"
        assert len(data["trains"]) == 1
        assert data["trains"][0]["number"] == "A1"
        assert data["trains"][0]["remaining"] == 1
        assert data["trains"][0]["approaching"] is True

    def test_api_failure(self, client, monkeypatch):
        monkeypatch.setattr(
            app_mod.manager, "get",
            lambda user_id: SimpleNamespace(
                config={"line_id": "Tozai", "line": "東西線",
                        "station": "木場", "destination": "", "train": ""},
                is_running=True,
            ),
        )

        def boom(session, api_id):
            raise ValueError("down")

        monkeypatch.setattr(app_mod, "fetch_line_data", boom)

        assert client.get("/track").status_code == 502


class TestStart:

    def test_valid(self, client):
        res = client.post("/start", data={
            "line": "Ginza",
            "station": "銀座",
            "destination": "浅草",
            "train": "a1234",
        })

        assert res.status_code == 200
        assert "銀座線 銀座 の監視を開始しました" in res.get_data(as_text=True)

        assert len(client.monitor_calls["start"]) == 1
        user_id, line, station, destination, train = \
            client.monitor_calls["start"][0]
        assert user_id  # Cookie由来の利用者IDが渡る
        assert line["id"] == "Ginza"
        assert station == "銀座"
        assert destination == "浅草"
        assert train == "A1234"  # 大文字に正規化される

    def test_empty_destination_ok(self, client):
        res = client.post("/start", data={
            "line": "Tozai",
            "station": "木場",
            "destination": "",
            "train": "",
        })
        assert res.status_code == 200
        assert len(client.monitor_calls["start"]) == 1

    def test_unknown_line(self, client):
        res = client.post("/start", data={
            "line": "Yamanote",
            "station": "木場",
            "destination": "",
            "train": "",
        })
        assert "路線を選択してください" in res.get_data(as_text=True)
        assert client.monitor_calls["start"] == []

    def test_station_not_on_line(self, client):
        # 銀座線に木場駅はない → 監視を開始してはいけない
        res = client.post("/start", data={
            "line": "Ginza",
            "station": "木場",
            "destination": "",
            "train": "",
        })
        assert "ありません" in res.get_data(as_text=True)
        assert client.monitor_calls["start"] == []

    def test_destination_not_on_line(self, client):
        res = client.post("/start", data={
            "line": "Ginza",
            "station": "銀座",
            "destination": "西船橋",
            "train": "",
        })
        assert "指定できません" in res.get_data(as_text=True)
        assert client.monitor_calls["start"] == []

    def test_invalid_train_number(self, client):
        res = client.post("/start", data={
            "line": "Tozai",
            "station": "木場",
            "destination": "",
            "train": "<script>!",
        })
        assert "列番は" in res.get_data(as_text=True)
        assert client.monitor_calls["start"] == []

    def test_missing_fields(self, client):
        res = client.post("/start", data={})
        assert res.status_code == 200
        assert client.monitor_calls["start"] == []

    def test_capacity_full(self, client, monkeypatch):
        monkeypatch.setattr(app_mod.manager, "start",
                            lambda *a, **k: False)

        res = client.post("/start", data={
            "line": "Tozai",
            "station": "木場",
            "destination": "",
            "train": "",
        })
        assert "利用者が多いため" in res.get_data(as_text=True)

    def test_switch_message_when_already_monitoring(self, client, monkeypatch):
        # 監視中に別の監視を開始したら「停止して切り替えた」ことを伝える
        monkeypatch.setattr(
            app_mod.manager, "get",
            lambda user_id: SimpleNamespace(
                config={"line": "銀座線", "station": "銀座"},
                is_running=True,
            ),
        )

        res = client.post("/start", data={
            "line": "Tozai",
            "station": "木場",
            "destination": "",
            "train": "",
        })

        text = res.get_data(as_text=True)
        assert "銀座線 銀座 の監視を停止し" in text
        assert "東西線 木場 の監視を開始しました" in text

    def test_start_resets_previous_alarm(self, client):
        # 前回の監視のアラームが鳴りっぱなしにならないこと
        client.post("/test")
        assert client.get("/status").get_json()["active"] is True

        client.post("/start", data={
            "line": "Tozai",
            "station": "木場",
            "destination": "",
            "train": "",
        })

        assert client.get("/status").get_json()["active"] is False


def test_stop(client):
    client.post("/test")

    res = client.post("/stop")

    assert res.status_code == 200
    assert len(client.monitor_calls["stop"]) == 1
    assert client.get("/status").get_json()["active"] is False


def test_status_shape(client):
    res = client.get("/status")
    data = res.get_json()

    assert set(data) == {
        "running", "config", "last_check",
        "active", "line", "station", "destination", "train",
    }
    assert data["running"] is False
    assert data["active"] is False
    assert data["config"] is None
    assert data["last_check"] is None


def test_test_alarm_and_ack(client):
    res = client.post("/test")
    assert res.status_code == 200

    status = client.get("/status").get_json()
    assert status["active"] is True
    assert status["train"] == "TEST123"

    history = client.get("/history").get_json()
    assert history[0]["train"] == "TEST123"
    assert history[0]["line"] == "テスト"
    assert history[0]["time"] != "TEST"  # 実時刻が入る

    client.post("/ack")
    assert client.get("/status").get_json()["active"] is False

    # ackしても履歴は残る
    assert len(client.get("/history").get_json()) == 1


def test_stats_excludes_test_entries(client):
    client.post("/test")

    stats = client.get("/stats").get_json()
    assert stats == {"today": 0, "total": 0}


# ----------------------
# 利用者分離
# ----------------------

class TestUserIsolation:

    def test_cookie_issued_once(self, client):
        res1 = client.get("/status")
        cookies = res1.headers.getlist("Set-Cookie")
        assert any(c.startswith("toyotyo_uid=") for c in cookies)

        # 2回目以降は再発行しない(IDが安定している)
        res2 = client.get("/status")
        assert res2.headers.getlist("Set-Cookie") == []

    def test_alarm_isolated(self, client):
        other = app.test_client()

        client.post("/test")

        assert client.get("/status").get_json()["active"] is True
        assert other.get("/status").get_json()["active"] is False

    def test_history_isolated(self, client):
        other = app.test_client()

        client.post("/test")

        assert len(client.get("/history").get_json()) == 1
        assert other.get("/history").get_json() == []

    def test_ack_isolated(self, client):
        # 他人のackで自分のアラームは消えない
        other = app.test_client()

        client.post("/test")
        other.post("/ack")

        assert client.get("/status").get_json()["active"] is True

    def test_stop_isolated(self, client):
        # 他人の停止操作は自分の監視に影響しない(自分のIDで呼ばれる)
        other = app.test_client()

        client.post("/test")
        other.post("/stop")

        assert client.get("/status").get_json()["active"] is True
        # manager.stop は other のIDで呼ばれている
        assert len(client.monitor_calls["stop"]) == 1

    def test_start_isolated_by_user_id(self, client):
        other = app.test_client()

        client.post("/start", data={
            "line": "Tozai", "station": "木場",
            "destination": "", "train": "",
        })
        other.post("/start", data={
            "line": "Ginza", "station": "銀座",
            "destination": "", "train": "",
        })

        starts = client.monitor_calls["start"]
        assert len(starts) == 2
        # 別々の利用者IDで開始されている
        assert starts[0][0] != starts[1][0]
