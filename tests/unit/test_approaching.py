"""接近（駅間）検知のテスト（Ver2）。

上流データの`now`は、1駅なら在線・2駅ならその区間を走行中を表す。
「駅間に入った時点」で鳴らせると、到着を待つより通知が1駅ぶん早くなる。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from toyocho.domain import (
    NOTIFY_APPROACHING,
    NOTIFY_ARRIVED,
    LineSnapshot,
    Subscription,
    TrainApproaching,
    TrainArrived,
    TrainDeparted,
    TrainSnapshot,
    diff_snapshots,
    matches,
)

LINE = "TokyoMetro_Tozai"
T0 = datetime(2026, 8, 7, 8, 0, 0)


def snap(stations, *, at=T0, train="A1234S"):
    return LineSnapshot(
        line_id=LINE,
        observed_at=at,
        trains=(
            TrainSnapshot(
                line_id=LINE,
                train_number=train,
                destination="西船橋",
                current_stations=frozenset(stations),
                direction="西船橋方面",
            ),
        ),
    )


def test_駅間に入ったら接近が出る():
    """★通知が1駅ぶん早くなる仕組み。"""
    before = snap(["東陽町"])
    after = snap(["東陽町", "南砂町"], at=T0 + timedelta(seconds=2))

    events = diff_snapshots(before, after)

    approaching = [e for e in events if isinstance(e, TrainApproaching)]
    assert len(approaching) == 1
    assert approaching[0].station_id == "南砂町"
    assert approaching[0].kind == NOTIFY_APPROACHING


def test_駅間から在線になったら到着が出る():
    before = snap(["東陽町", "南砂町"])
    after = snap(["南砂町"], at=T0 + timedelta(seconds=2))

    events = diff_snapshots(before, after)

    arrived = [e for e in events if isinstance(e, TrainArrived)]
    assert len(arrived) == 1
    assert arrived[0].station_id == "南砂町"
    assert arrived[0].kind == NOTIFY_ARRIVED


def test_駅間の間は接近を繰り返さない():
    """走行中の状態が続いても、接近は最初の1回だけ。"""
    before = snap(["東陽町", "南砂町"])
    after = snap(["東陽町", "南砂町"], at=T0 + timedelta(seconds=2))

    assert diff_snapshots(before, after) == []


def test_接近から到着までの一連の流れ():
    s1 = snap(["東陽町"])
    s2 = snap(["東陽町", "南砂町"], at=T0 + timedelta(seconds=2))
    s3 = snap(["南砂町"], at=T0 + timedelta(seconds=4))

    e1 = diff_snapshots(s1, s2)
    e2 = diff_snapshots(s2, s3)

    # 駅間に入った時点で「東陽町を出発」と「南砂町へ接近」が同時に起きる。
    # 出発の記録があることで、この列車が次に東陽町へ来たときにまた鳴らせる。
    assert sorted(type(e).__name__ for e in e1) == ["TrainApproaching", "TrainDeparted"]
    assert any(isinstance(e, TrainApproaching) and e.station_id == "南砂町" for e in e1)
    assert any(isinstance(e, TrainDeparted) and e.station_id == "東陽町" for e in e1)

    # 在線に変われば到着（この時点で新たな出発はない）
    assert [type(e).__name__ for e in e2] == ["TrainArrived"]
    assert e2[0].station_id == "南砂町"


def test_通知タイミングを選べる():
    到着だけ = Subscription(
        id="s1",
        user_id="u1",
        line_id=LINE,
        station_id="南砂町",
        notify_on=frozenset({NOTIFY_ARRIVED}),
    )
    接近 = TrainApproaching(
        line_id=LINE, train_number="A1", occurred_at=T0, station_id="南砂町", destination="西船橋"
    )
    到着 = TrainArrived(
        line_id=LINE, train_number="A1", occurred_at=T0, station_id="南砂町", destination="西船橋"
    )

    assert matches(到着だけ, 接近, T0) is False
    assert matches(到着だけ, 到着, T0) is True


def test_既定では早いほうで鳴る():
    """既定は接近・到着の両方が対象。重複排除により、実際に鳴るのは先に来た1回だけ
    （その確認は test_service.py で行う）。"""
    sub = Subscription(id="s1", user_id="u1", line_id=LINE, station_id="南砂町")
    接近 = TrainApproaching(
        line_id=LINE, train_number="A1", occurred_at=T0, station_id="南砂町", destination="西船橋"
    )

    assert matches(sub, 接近, T0) is True
