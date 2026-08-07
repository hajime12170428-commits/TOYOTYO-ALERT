"""一致判定のテスト（Ver2 Phase1）。

複数利用者・複数路線が正しく分かれること（＝他人の条件で鳴らないこと）を確かめる。
"""

from __future__ import annotations

from datetime import datetime, time

from toyocho.domain import (
    ActiveSchedule,
    Subscription,
    TrainArrived,
    TrainDeparted,
    find_matches,
    matches,
)

NOW = datetime(2026, 8, 6, 8, 30)  # 木曜 8:30


def sub(**kwargs):
    base = dict(
        id="s1",
        user_id="u1",
        line_id="TokyoMetro_Tozai",
        station_id="木場",
    )
    base.update(kwargs)
    return Subscription(**base)


def arrived(**kwargs):
    base = dict(
        line_id="TokyoMetro_Tozai",
        train_number="A1234S",
        occurred_at=NOW,
        station_id="木場",
        destination="西船橋",
        direction="下り",
    )
    base.update(kwargs)
    return TrainArrived(**base)


def test_条件を指定しなければすべての列車で鳴る():
    assert matches(sub(), arrived(), NOW) is True


def test_路線が違えば鳴らない():
    assert matches(sub(line_id="JR_Chuo"), arrived(), NOW) is False


def test_駅が違えば鳴らない():
    assert matches(sub(station_id="南砂町"), arrived(), NOW) is False


def test_行先で絞り込める():
    assert matches(sub(destination="西船橋"), arrived(), NOW) is True
    assert matches(sub(destination="中野"), arrived(), NOW) is False


def test_列車番号で絞り込める():
    assert matches(sub(train_number="A1234S"), arrived(), NOW) is True
    assert matches(sub(train_number="B9999S"), arrived(), NOW) is False


def test_方面で絞り込める():
    assert matches(sub(direction="下り"), arrived(), NOW) is True
    assert matches(sub(direction="上り"), arrived(), NOW) is False


def test_停止中の購読では鳴らない():
    assert matches(sub(active=False), arrived(), NOW) is False


def test_出発では鳴らない():
    departed = TrainDeparted(
        line_id="TokyoMetro_Tozai", train_number="A1234S", occurred_at=NOW, station_id="木場"
    )

    assert matches(sub(), departed, NOW) is False


def test_時間帯の外では鳴らない():
    朝だけ = ActiveSchedule(start=time(7, 0), end=time(9, 0))

    assert matches(sub(schedule=朝だけ), arrived(), NOW) is True
    assert matches(sub(schedule=朝だけ), arrived(), datetime(2026, 8, 6, 10, 0)) is False


def test_複数の利用者のうち条件に合う人だけが鳴る():
    """★複数利用者対応の核心。他人の条件で鳴らないこと。"""
    subs = [
        sub(id="s1", user_id="u1"),                                # 木場・条件なし
        sub(id="s2", user_id="u2", destination="中野"),             # 行先違い
        sub(id="s3", user_id="u3", station_id="南砂町"),            # 駅違い
        sub(id="s4", user_id="u4", destination="西船橋"),           # 一致
        sub(id="s5", user_id="u5", active=False),                  # 停止中
    ]

    hit = find_matches(subs, arrived(), NOW)

    assert [s.id for s in hit] == ["s1", "s4"]
