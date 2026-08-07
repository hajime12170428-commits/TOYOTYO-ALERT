# 監視対象列車の位置計算(tracking.py)のテスト
from tracking import AVG_MINUTES_PER_STATION, build_train_status, select_tracked

# 東西線の一部(index: 中野0, 落合1, 高田馬場2, 早稲田3, 神楽坂4)
LINE = {
    "id": "Tozai",
    "name": "東西線",
    "stations": ["中野", "落合", "高田馬場", "早稲田", "神楽坂"],
}


def train(number="A1", destination="中野", now=None, direction_text=""):
    return {
        "number": number,
        "type": "普通",
        "destination": destination,
        "now": now or [],
        "direction_text": direction_text,
        "delay_text": "",
    }


class TestBuildTrainStatus:

    def test_moving_toward_target(self):
        # 神楽坂→早稲田を走行中、監視駅は落合 → 早稲田・高田馬場・落合であと3駅
        t = train(now=["神楽坂", "早稲田"])
        s = build_train_status(LINE, "落合", t)

        assert s["position"] == "神楽坂→早稲田"
        assert s["next_station"] == "早稲田"
        assert s["remaining"] == 3
        assert s["approaching"] is True
        assert s["eta_minutes"] == 3 * AVG_MINUTES_PER_STATION

    def test_moving_next_is_target(self):
        t = train(now=["高田馬場", "落合"])
        s = build_train_status(LINE, "落合", t)

        assert s["remaining"] == 1
        assert s["approaching"] is True
        assert s["eta_minutes"] == AVG_MINUTES_PER_STATION

    def test_moving_away_from_target(self):
        # 落合→高田馬場(中野と逆方向)を走行中、監視駅は中野
        t = train(number="B1", destination="西船橋", now=["落合", "高田馬場"])
        s = build_train_status(LINE, "中野", t)

        assert s["approaching"] is False
        assert s["eta_minutes"] is None

    def test_stopped_at_target(self):
        t = train(now=["落合"])
        s = build_train_status(LINE, "落合", t)

        assert s["remaining"] == 0
        assert s["approaching"] is True

    def test_stopped_direction_from_destination(self):
        # 早稲田に停車中・中野行 → 次は高田馬場、落合まであと2駅
        t = train(now=["早稲田"], destination="中野")
        s = build_train_status(LINE, "落合", t)

        assert s["next_station"] == "高田馬場"
        assert s["remaining"] == 2
        assert s["approaching"] is True

    def test_stopped_direction_from_direction_text(self):
        # 行先が路線外(直通先)でも「○○方面」から方向を推定できる
        t = train(now=["早稲田"], destination="三鷹", direction_text="中野方面")
        s = build_train_status(LINE, "落合", t)

        assert s["next_station"] == "高田馬場"
        assert s["approaching"] is True

    def test_stopped_direction_unknown(self):
        # 方向が判定できない場合は approaching = None
        t = train(now=["早稲田"], destination="三鷹", direction_text="")
        s = build_train_status(LINE, "落合", t)

        assert s["approaching"] is None
        assert s["eta_minutes"] is None
        assert s["remaining"] == 2  # 距離自体は出せる

    def test_outside_line(self):
        # 直通先など路線外の在線位置
        t = train(now=["三鷹"])
        s = build_train_status(LINE, "落合", t)

        assert s["position"] == "三鷹"
        assert s["remaining"] is None
        assert s["approaching"] is None

    def test_empty_position(self):
        s = build_train_status(LINE, "落合", train(now=[]))
        assert s["position"] == "不明"
        assert s["remaining"] is None
        assert s["direction"] == 0
        assert s["now_stations"] == []

    # ---- 路線図表示用フィールド ----

    def test_direction_and_now_stations(self):
        # 神楽坂→早稲田(中野方向)は direction = -1
        s = build_train_status(LINE, "落合", train(now=["神楽坂", "早稲田"]))
        assert s["direction"] == -1
        assert s["now_stations"] == ["神楽坂", "早稲田"]

        # 落合→高田馬場(神楽坂方向)は direction = +1
        s = build_train_status(
            LINE, "中野",
            train(destination="西船橋", now=["落合", "高田馬場"]),
        )
        assert s["direction"] == 1

    def test_end_station_is_online_destination(self):
        # 行先(中野)が路線上 → 終点=中野、早稲田→高田馬場走行中で残り3駅
        s = build_train_status(LINE, "落合", train(now=["早稲田", "高田馬場"]))
        assert s["end_station"] == "中野"
        assert s["end_remaining"] == 3  # 高田馬場・落合・中野

    def test_end_station_falls_back_to_line_end(self):
        # 直通先行き(三鷹)は路線端(中野)を終点扱いにする
        s = build_train_status(
            LINE, "落合",
            train(now=["早稲田"], destination="三鷹",
                  direction_text="中野方面"),
        )
        assert s["end_station"] == "中野"
        assert s["end_remaining"] == 3  # 早稲田から高田馬場・落合・中野

    def test_end_station_zero_at_terminus(self):
        s = build_train_status(LINE, "落合", train(now=["中野"],
                                                   destination="中野"))
        assert s["end_remaining"] == 0

    def test_end_unknown_without_direction(self):
        s = build_train_status(
            LINE, "落合",
            train(now=["早稲田"], destination="三鷹", direction_text=""),
        )
        assert s["end_station"] is None
        assert s["end_remaining"] is None


class TestSelectTracked:

    def cfg(self, station="落合", destination="", train_no=""):
        return {"station": station, "destination": destination,
                "train": train_no}

    def test_specific_train_always_shown(self):
        # 列番指定なら逆方向でも表示する
        trains = [
            train(number="B1", destination="西船橋", now=["落合", "高田馬場"]),
        ]
        infos = select_tracked(LINE, self.cfg("中野", train_no="B1"), trains)

        assert len(infos) == 1
        assert infos[0]["approaching"] is False

    def test_unspecified_shows_only_approaching_sorted(self):
        trains = [
            train(number="FAR", now=["神楽坂", "早稲田"]),      # あと3駅
            train(number="NEAR", now=["高田馬場", "落合"]),     # あと1駅
            train(number="AWAY", destination="西船橋",
                  now=["落合", "高田馬場"]),                     # 逆方向
        ]
        infos = select_tracked(LINE, self.cfg("落合"), trains)

        assert [i["number"] for i in infos] == ["NEAR", "FAR"]

    def test_destination_filter_applied(self):
        trains = [
            train(number="A1", destination="中野", now=["早稲田", "高田馬場"]),
            train(number="A2", destination="三鷹", now=["神楽坂", "早稲田"],
                  direction_text="中野方面"),
        ]
        infos = select_tracked(LINE, self.cfg("落合", destination="中野"),
                               trains)

        assert [i["number"] for i in infos] == ["A1"]

    def test_limit(self):
        trains = [
            train(number=f"T{i}", now=["神楽坂", "早稲田"]) for i in range(10)
        ]
        infos = select_tracked(LINE, self.cfg("落合"), trains, limit=5)
        assert len(infos) == 5
