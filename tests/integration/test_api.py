"""HTTPの入口のテスト（Ver2）。本物の上流には接続しない。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from toyocho import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{tmp_path/'api.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(store, "engine", engine)
    monkeypatch.setattr(
        store, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    store.Base.metadata.create_all(bind=engine)

    from toyocho import api

    # 巡回（本物の上流への接続）は止めておく
    monkeypatch.setattr(api.poller, "start", lambda: None)

    async def _noop():
        return None

    monkeypatch.setattr(api.poller, "stop", _noop)
    monkeypatch.setattr(api.feed, "aclose", _noop)

    with TestClient(api.app) as c:
        yield c


def test_全路線が返る(client):
    lines = client.get("/api/lines").json()

    assert len(lines) == 10
    tozai = [l for l in lines if l["id"] == "TokyoMetro_Tozai"][0]
    assert tozai["name"] == "東西線"
    assert "東陽町" in tozai["stations"]
    assert tozai["directions"] == ["中野方面", "西船橋方面"]


def test_登録なしで見張りを作れる(client):
    """★登録の手間をなくすため、最初のアクセスで利用者を自動で作る。"""
    r = client.post(
        "/api/subscriptions", json={"line_id": "TokyoMetro_Tozai", "station_id": "東陽町"}
    )

    assert r.status_code == 201
    assert r.json()["line_name"] == "東西線"
    assert client.cookies.get("toyocho_user")


def test_存在しない駅は断る(client):
    r = client.post(
        "/api/subscriptions", json={"line_id": "TokyoMetro_Tozai", "station_id": "渋谷"}
    )

    assert r.status_code == 400
    assert "ありません" in r.json()["detail"]


def test_取り扱っていない路線は断る(client):
    r = client.post("/api/subscriptions", json={"line_id": "JR_Yamanote", "station_id": "渋谷"})

    assert r.status_code == 400


def test_方面の誤りを断る(client):
    r = client.post(
        "/api/subscriptions",
        json={"line_id": "TokyoMetro_Tozai", "station_id": "東陽町", "direction": "浅草方面"},
    )

    assert r.status_code == 400


def test_他人の見張りは見えないし消せない(client):
    """★複数利用者対応の要。"""
    created = client.post(
        "/api/subscriptions", json={"line_id": "TokyoMetro_Tozai", "station_id": "東陽町"}
    ).json()

    client.cookies.clear()  # 別の端末として振る舞う

    assert client.get("/api/subscriptions").json() == []
    assert client.delete(f"/api/subscriptions/{created['id']}").status_code == 404


def test_停止と再開ができる(client):
    created = client.post(
        "/api/subscriptions", json={"line_id": "TokyoMetro_Tozai", "station_id": "東陽町"}
    ).json()

    assert client.patch(f"/api/subscriptions/{created['id']}?active=false").json()["active"] is False
    assert client.patch(f"/api/subscriptions/{created['id']}?active=true").json()["active"] is True


def test_削除できる(client):
    created = client.post(
        "/api/subscriptions", json={"line_id": "TokyoMetro_Tozai", "station_id": "東陽町"}
    ).json()

    assert client.delete(f"/api/subscriptions/{created['id']}").status_code == 204
    assert client.get("/api/subscriptions").json() == []


def test_実時間の接続で利用者が固定される():
    """★不具合の再発防止：SSEのように応答を自分で組み立てる場所でも、
    初回のCookieが付くこと。付かないと、つなぎ直すたびに別人になり履歴が分かれる。

    （SSEは終わらない通信のため、実際に接続せず、
    　Cookieを付け直す部分だけを取り出して確かめる。）
    """
    from types import SimpleNamespace

    from fastapi.responses import StreamingResponse

    from toyocho.api import attach_new_user_cookie

    request = SimpleNamespace(state=SimpleNamespace(new_user_id="abc123"))
    response = attach_new_user_cookie(request, StreamingResponse(iter(())))
    assert "toyocho_user=abc123" in response.headers.get("set-cookie", "")

    # 2回目以降（すでにCookieがある端末）には付け直さない
    request2 = SimpleNamespace(state=SimpleNamespace(new_user_id=None))
    response2 = attach_new_user_cookie(request2, StreamingResponse(iter(())))
    assert "set-cookie" not in response2.headers


def test_状態確認が返る(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert "subscriptions" in body


def test_画面が返る(client):
    assert client.get("/").status_code == 200
    assert client.get("/manifest.json").status_code == 200
    assert client.get("/sw.js").status_code == 200
