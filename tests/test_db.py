# SQLite データ層のテスト
import pytest

import db
from timeutil import now_str


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()


def entry(train="A1234S", line="東西線", station="木場", destination="西船橋"):
    return {
        "time": now_str(),
        "line": line,
        "station": station,
        "destination": destination,
        "train": train,
    }


def test_ensure_user_idempotent():
    db.ensure_user("user-1")
    db.ensure_user("user-1")  # 2回呼んでもエラーにならない


def test_history_roundtrip():
    db.add_history("user-1", entry())

    rows = db.get_history("user-1")
    assert len(rows) == 1
    assert rows[0]["train"] == "A1234S"
    assert set(rows[0]) == {"time", "line", "station", "destination", "train"}


def test_history_newest_first_and_limited():
    for i in range(150):
        db.add_history("user-1", entry(train=f"T{i}"))

    rows = db.get_history("user-1")
    assert len(rows) == db.HISTORY_PAGE_LIMIT
    assert rows[0]["train"] == "T149"  # 新しい順


def test_history_isolated_between_users():
    db.add_history("user-a", entry(train="AAA"))
    db.add_history("user-b", entry(train="BBB"))

    assert [r["train"] for r in db.get_history("user-a")] == ["AAA"]
    assert [r["train"] for r in db.get_history("user-b")] == ["BBB"]


def test_stats_per_user_and_excludes_tests():
    db.add_history("user-a", entry())
    db.add_history("user-a", entry())
    db.add_history("user-a", entry(train="TEST123"), is_test=True)
    db.add_history("user-b", entry())

    stats_a = db.get_stats("user-a")
    assert stats_a["total"] == 2  # テスト通知は数えない
    assert stats_a["today"] == 2

    assert db.get_stats("user-b")["total"] == 1
    assert db.get_stats("user-c")["total"] == 0


def test_stats_today_excludes_past_days():
    old = entry()
    old["time"] = "2000-01-01 09:00:00"
    db.add_history("user-1", old)
    db.add_history("user-1", entry())

    stats = db.get_stats("user-1")
    assert stats["total"] == 2
    assert stats["today"] == 1


def test_monitor_state_lifecycle():
    assert db.get_active_monitors() == []

    db.save_monitor("user-1", "Tozai", "木場", "", "")
    db.save_monitor("user-2", "Ginza", "銀座", "浅草", "A1")

    active = db.get_active_monitors()
    assert len(active) == 2

    # 同じ利用者の保存は上書き(1利用者1監視)
    db.save_monitor("user-1", "Hibiya", "上野", "", "")
    active = {m["user_id"]: m for m in db.get_active_monitors()}
    assert len(active) == 2
    assert active["user-1"]["line_id"] == "Hibiya"

    db.deactivate_monitor("user-1")
    remaining = db.get_active_monitors()
    assert [m["user_id"] for m in remaining] == ["user-2"]
