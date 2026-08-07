"""差分検出のテスト（Ver2 Phase1）。

**Ver1で実際に起きていた不具合の再発防止**が主目的：
- 駅に停まっている間、2秒ごとに何度も鳴った
- サーバーを再起動すると、同じ列車でまた鳴った
- 起動した瞬間、たまたま在線中の列車で鳴った
"""

from __future__ import annotations

from datetime import datetime, timedelta

from toyocho.domain import (
    DelayChanged,
    LineSnapshot,
    TrainArrived,
    TrainDeparted,
    TrainSnapshot,
    diff_snapshots,
)

LINE = "TokyoMetro_Tozai"
T0 = datetime(2026, 8, 6, 8, 0, 0)


def snapshot(stations, *, at=T0, train="A1234S", destination="西船橋", delay=0):
    return LineSnapshot(
        line_id=LINE,
        observed_at=at,
        trains=(
            TrainSnapshot(
                line_id=LINE,
                train_number=train,
                destination=destination,
                current_stations=frozenset(stations),
                delay_minutes=delay,
            ),
        ),
    )


def test_初回は鳴らさない():
    """起動直後に在線している列車で、いっせいに鳴らないこと。"""
    events = diff_snapshots(None, snapshot(["木場"]))

    assert events == []


def test_初回でも明示すれば鳴らせる():
    events = diff_snapshots(None, snapshot(["木場"]), emit_initial_arrivals=True)

    assert len(events) == 1
    assert isinstance(events[0], TrainArrived)


def test_駅に入ったら到着が1件だけ出る():
    before = snapshot(["東陽町"])
    after = snapshot(["木場"], at=T0 + timedelta(seconds=2))

    events = diff_snapshots(before, after)

    arrived = [e for e in events if isinstance(e, TrainArrived)]
    assert len(arrived) == 1
    assert arrived[0].station_id == "木場"
    assert arrived[0].destination == "西船橋"


def test_停まり続けても二度目は出ない():
    """★Ver1の最大の不具合の再発防止。"""
    before = snapshot(["木場"])
    after = snapshot(["木場"], at=T0 + timedelta(seconds=2))

    events = diff_snapshots(before, after)

    assert [e for e in events if isinstance(e, TrainArrived)] == []


def test_離れてからまた来たら再び鳴る():
    at_station = snapshot(["木場"])
    left = snapshot(["南砂町"], at=T0 + timedelta(seconds=2))
    returned = snapshot(["木場"], at=T0 + timedelta(seconds=4))

    departed = diff_snapshots(at_station, left)
    arrived_again = diff_snapshots(left, returned)

    assert any(isinstance(e, TrainDeparted) and e.station_id == "木場" for e in departed)
    assert any(isinstance(e, TrainArrived) and e.station_id == "木場" for e in arrived_again)


def test_一覧から消えた列車は出発とみなす():
    before = snapshot(["木場"])
    after = LineSnapshot(line_id=LINE, observed_at=T0 + timedelta(seconds=2), trains=())

    events = diff_snapshots(before, after)

    assert len(events) == 1
    assert isinstance(events[0], TrainDeparted)
    assert events[0].station_id == "木場"


def test_遅延の変化を検知する():
    before = snapshot(["木場"], delay=0)
    after = snapshot(["木場"], at=T0 + timedelta(seconds=2), delay=5)

    events = diff_snapshots(before, after)

    changed = [e for e in events if isinstance(e, DelayChanged)]
    assert len(changed) == 1
    assert changed[0].previous_minutes == 0
    assert changed[0].current_minutes == 5


def test_複数の列車を同時に扱える():
    before = LineSnapshot(line_id=LINE, observed_at=T0, trains=())
    after = LineSnapshot(
        line_id=LINE,
        observed_at=T0 + timedelta(seconds=2),
        trains=(
            TrainSnapshot(LINE, "A1", "西船橋", frozenset(["木場"])),
            TrainSnapshot(LINE, "B2", "中野", frozenset(["東陽町"])),
        ),
    )

    events = diff_snapshots(before, after)

    arrived = sorted(
        (e for e in events if isinstance(e, TrainArrived)), key=lambda e: e.train_number
    )
    assert [e.train_number for e in arrived] == ["A1", "B2"]
    assert [e.station_id for e in arrived] == ["木場", "東陽町"]
