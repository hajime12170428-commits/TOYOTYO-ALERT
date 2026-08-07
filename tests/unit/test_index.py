"""購読索引のテスト（Ver2 Phase1）。数万人規模での引き当てを確かめる。"""

from __future__ import annotations

import time
from datetime import datetime

from toyocho.domain import Subscription, SubscriptionIndex, TrainArrived, find_matches

NOW = datetime(2026, 8, 6, 8, 30)


def _sub(sub_id, station="木場", line="Tozai", active=True):
    return Subscription(
        id=sub_id, user_id=f"u{sub_id}", line_id=line, station_id=station, active=active
    )


def _arrived(station="木場", line="Tozai"):
    return TrainArrived(
        line_id=line,
        train_number="A1234S",
        occurred_at=NOW,
        station_id=station,
        destination="西船橋",
    )


def test_駅ごとに引き当てられる():
    index = SubscriptionIndex([_sub("1", "木場"), _sub("2", "南砂町"), _sub("3", "木場")])

    hit = index.find("Tozai", "木場")

    assert sorted(s.id for s in hit) == ["1", "3"]


def test_停止中の購読は索引に入らない():
    index = SubscriptionIndex([_sub("1"), _sub("2", active=False)])

    assert [s.id for s in index.find("Tozai", "木場")] == ["1"]


def test_追加と削除ができる():
    index = SubscriptionIndex()
    index.add(_sub("1"))
    assert len(index.find("Tozai", "木場")) == 1

    index.remove("1")
    assert index.find("Tozai", "木場") == []


def test_同じIDで追加し直すと置き換わる():
    index = SubscriptionIndex([_sub("1", "木場")])
    index.add(_sub("1", "南砂町"))

    assert index.find("Tozai", "木場") == []
    assert len(index.find("Tozai", "南砂町")) == 1


def test_見張り中の路線が分かる():
    """購読ゼロの路線には上流へ問い合わせないための情報。"""
    index = SubscriptionIndex([_sub("1", line="Tozai"), _sub("2", line="Chuo")])

    assert index.watched_lines() == {"Tozai", "Chuo"}


def test_十万件でも引き当てが速い():
    """★数万人対応の裏づけ。購読が増えても1件あたりの処理時間が伸びないこと。"""
    subs = [_sub(str(i), station=f"駅{i % 500}") for i in range(100_000)]
    index = SubscriptionIndex(subs)
    assert len(index) == 100_000

    started = time.perf_counter()
    for _ in range(10_000):
        index.find("Tozai", "駅123")
    elapsed = time.perf_counter() - started

    # 10,000回の引き当てが1秒未満（実測では数ミリ秒。環境差を考えて緩めの上限）
    assert elapsed < 1.0
    assert len(index.find("Tozai", "駅123")) == 200


def test_索引と判定を組み合わせて必要な人にだけ届く():
    subs = [
        _sub("1", "木場"),
        _sub("2", "南砂町"),
        Subscription(
            id="3", user_id="u3", line_id="Tozai", station_id="木場", destination="中野"
        ),
    ]
    index = SubscriptionIndex(subs)
    event = _arrived()

    候補 = index.candidates_for(event)
    確定 = find_matches(候補, event, NOW)

    assert [s.id for s in 候補] == ["1", "3"]  # 索引で駅違いを除外
    assert [s.id for s in 確定] == ["1"]  # 判定で行先違いを除外
