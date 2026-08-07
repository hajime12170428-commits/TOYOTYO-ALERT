"""有効時間帯と重複排除のテスト（Ver2 Phase1）。"""

from __future__ import annotations

from datetime import datetime, time

from toyocho.domain import (
    ActiveSchedule,
    InMemoryDedupeStore,
    Subscription,
    TrainArrived,
    dedupe_key,
)

# 2026-08-06 は木曜日
木曜朝 = datetime(2026, 8, 6, 8, 30)
土曜朝 = datetime(2026, 8, 8, 8, 30)


def test_既定は終日毎日有効():
    assert ActiveSchedule().is_active_at(木曜朝) is True
    assert ActiveSchedule().is_active_at(土曜朝) is True


def test_平日だけ有効にできる():
    平日 = ActiveSchedule(weekdays=frozenset({0, 1, 2, 3, 4}))

    assert 平日.is_active_at(木曜朝) is True
    assert 平日.is_active_at(土曜朝) is False


def test_時間帯で絞れる():
    朝 = ActiveSchedule(start=time(7, 0), end=time(9, 0))

    assert 朝.is_active_at(datetime(2026, 8, 6, 6, 59)) is False
    assert 朝.is_active_at(datetime(2026, 8, 6, 7, 0)) is True
    assert 朝.is_active_at(datetime(2026, 8, 6, 8, 59)) is True
    assert 朝.is_active_at(datetime(2026, 8, 6, 9, 0)) is False


def test_日をまたぐ時間帯を扱える():
    """22:00〜翌6:00のような帯（終電前の見張り等）。"""
    夜間 = ActiveSchedule(start=time(22, 0), end=time(6, 0))

    assert 夜間.is_active_at(datetime(2026, 8, 6, 23, 30)) is True
    assert 夜間.is_active_at(datetime(2026, 8, 6, 5, 30)) is True
    assert 夜間.is_active_at(datetime(2026, 8, 6, 12, 0)) is False


# ---- 重複排除 ----


class 手動時計:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def 進める(self, 秒: float) -> None:
        self.now += 秒


def _sub(sub_id="s1"):
    return Subscription(id=sub_id, user_id="u1", line_id="L", station_id="木場")


def _event(train="A1234S"):
    return TrainArrived(
        line_id="L",
        train_number=train,
        occurred_at=木曜朝,
        station_id="木場",
        destination="西船橋",
    )


def test_同じ組み合わせは一度しか通らない():
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)
    key = dedupe_key(_sub(), _event())

    assert store.acquire(key) is True
    assert store.acquire(key) is False


def test_期限が切れれば再び通る():
    """列車が一周して戻ってきた場合などに、また鳴らせること。"""
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)
    key = dedupe_key(_sub(), _event())

    assert store.acquire(key, ttl_seconds=900) is True
    clock.進める(901)
    assert store.acquire(key, ttl_seconds=900) is True


def test_購読が違えば互いに影響しない():
    """★複数利用者対応：Aさんに鳴ったせいでBさんが鳴らない、が起きないこと。"""
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)

    assert store.acquire(dedupe_key(_sub("s1"), _event())) is True
    assert store.acquire(dedupe_key(_sub("s2"), _event())) is True


def test_列車が違えば別扱い():
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)
    sub = _sub()

    assert store.acquire(dedupe_key(sub, _event("A1"))) is True
    assert store.acquire(dedupe_key(sub, _event("B2"))) is True
