"""取り込み→判定→配信の通しテスト（Ver2）。

本物の通信・本物の携帯通知は使わず、偽物を差し込んで確かめる。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from toyocho import store
from toyocho.domain import LineSnapshot, TrainSnapshot
from toyocho.feed import FeedResult, parse
from toyocho.notify import LiveConnections
from toyocho.service import AlertService, Poller

LINE = "TokyoMetro_Tozai"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """テストごとに空のデータベースを使う。"""
    engine_url = f"sqlite:///{tmp_path/'test.db'}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(engine_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(store, "engine", engine)
    monkeypatch.setattr(store, "SessionLocal", Session)
    store.Base.metadata.create_all(bind=engine)
    yield


class _沈黙するPush:
    enabled = False

    def send(self, *a, **k):
        return False


def _購読を作る(**kwargs):
    with store.get_session() as db:
        user = store.create_user(db)
        row = store.SubscriptionRow(
            user_id=user.id,
            line_id=kwargs.pop("line_id", LINE),
            station_id=kwargs.pop("station_id", "木場"),
            notify_on=kwargs.pop("notify_on", "approaching,arrived"),
            **kwargs,
        )
        db.add(row)
        db.commit()
        return user.id, row.id


def _result(stations, *, version, train="A1234S"):
    return FeedResult(
        snapshot=LineSnapshot(
            line_id=LINE,
            observed_at=datetime(2026, 8, 7, 8, 0, 0),
            trains=(
                TrainSnapshot(
                    line_id=LINE,
                    train_number=train,
                    destination="西船橋",
                    current_stations=frozenset(stations),
                    direction="西船橋方面",
                ),
            ),
        ),
        version=version,
    )


def _service():
    svc = AlertService(live=LiveConnections(), push=_沈黙するPush())
    svc.reload_subscriptions()
    return svc


def test_条件に合う人にだけ通知が届く():
    user_a, _ = _購読を作る(station_id="木場")
    user_b, _ = _購読を作る(station_id="南砂町")
    svc = _service()

    queue_a = svc.live.connect(user_a)
    queue_b = svc.live.connect(user_b)

    svc.handle_snapshot(_result(["東陽町"], version=1))  # 基準
    fired = svc.handle_snapshot(_result(["木場"], version=2))

    assert fired == 1
    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 0
    assert "木場" in queue_a.get_nowait()


def test_同じ列車で二度鳴らない():
    """★Ver1の最大の不具合の再発防止（通しでの確認）。"""
    user, _ = _購読を作る(station_id="木場")
    svc = _service()
    queue = svc.live.connect(user)

    svc.handle_snapshot(_result(["東陽町"], version=1))
    svc.handle_snapshot(_result(["東陽町", "木場"], version=2))  # 接近で1回
    svc.handle_snapshot(_result(["木場"], version=3))  # 到着では鳴らない
    svc.handle_snapshot(_result(["木場"], version=4))  # 停まり続けても鳴らない

    assert queue.qsize() == 1
    assert '"kind": "approaching"' in queue.get_nowait().replace("'", '"')


def test_上流が更新されていなければ何もしない():
    _購読を作る()
    svc = _service()

    svc.handle_snapshot(_result(["東陽町"], version=10))
    svc.handle_snapshot(_result(["木場"], version=10))  # 同じ版＝更新なし

    assert svc.stats["skipped_unchanged"] == 1


def test_通知が履歴に残る():
    user, sub_id = _購読を作る(station_id="木場")
    svc = _service()

    svc.handle_snapshot(_result(["東陽町"], version=1))
    svc.handle_snapshot(_result(["木場"], version=2))

    with store.get_session() as db:
        rows = db.query(store.AlertRow).all()
    assert len(rows) == 1
    assert rows[0].station_id == "木場"
    assert rows[0].user_id == user
    assert rows[0].subscription_id == sub_id


def test_見張っている路線だけを取りに行く():
    """★数万人対応の要：購読ゼロの路線には問い合わせない。"""
    _購読を作る(line_id=LINE)
    svc = _service()

    assert svc.watched_lines() == [LINE]


def test_購読がなければ上流に一切問い合わせない():
    svc = _service()

    class _呼ばれたら失敗するfeed:
        async def fetch(self, line_id):
            raise AssertionError("購読ゼロなのに問い合わせた")

    poller = Poller(svc, _呼ばれたら失敗するfeed())
    assert asyncio.run(poller.run_once()) == 0


def test_一つの路線が失敗しても他は続く():
    _購読を作る(line_id="TokyoMetro_Tozai")
    _購読を作る(line_id="TokyoMetro_Ginza", station_id="渋谷")
    svc = _service()

    class _片方だけ壊れるfeed:
        async def fetch(self, line_id):
            if line_id == "TokyoMetro_Ginza":
                raise ConnectionError("上流に届きません")
            return _result(["木場"], version=99)

    poller = Poller(svc, _片方だけ壊れるfeed())
    asyncio.run(poller.run_once())  # 例外が外に出ないこと

    assert svc.stats["polls"] == 1  # 生きているほうは処理された


def test_実データの形をそのまま扱える():
    """上流の生データ（実際の項目名）から正しく読み取れること。"""
    payload = {
        "update": 1786089862000,
        "running": [],
        "noRunning": [
            {
                "line_id": "TokyoMetro.Tozai",
                "now": ["中野", "落合"],
                "number": "B1677S",
                "destination": "中野",
                "direction_text": "中野方面",
                "delay_value": 3,
            }
        ],
    }

    result = parse(LINE, payload)

    assert result.version == 1786089862000
    train = result.snapshot.trains[0]
    assert train.train_number == "B1677S"
    assert train.current_stations == frozenset({"中野", "落合"})
    assert train.direction == "中野方面"
    assert train.delay_minutes == 3
