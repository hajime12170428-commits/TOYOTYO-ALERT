"""HTTPの入口（Ver2）。FastAPI。

利用者は**登録なしで**使い始められる（端末ごとに自動で利用者を作る）。
合言葉は端末に保存され、以降の呼び出しで自分の購読だけが見える。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import metro, store
from .domain.models import NOTIFY_DEFAULT
from .feed import MetroFeed
from .notify import VAPID_PUBLIC_KEY
from .service import AlertService, Poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

USER_COOKIE = "toyocho_user"
COOKIE_MAX_AGE = 400 * 24 * 60 * 60  # 約400日（ブラウザの上限）
# 本番（HTTPS）では暗号化された通信でしか合言葉を送らない。
# 手元での開発（http://localhost）でこれを有効にすると保存されず、動かなくなる。
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

service = AlertService()
feed = MetroFeed()
poller = Poller(service, feed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    service.reload_subscriptions()
    poller.start()
    yield
    await poller.stop()
    await feed.aclose()


app = FastAPI(title="TOYOCHO ALERT", version="2.0.0", lifespan=lifespan)


def get_db():
    db = store.get_session()
    try:
        yield db
    finally:
        db.close()


def _set_user_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        USER_COOKIE,
        user_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def attach_new_user_cookie(request: Request, response: Response) -> Response:
    """応答を自分で組み立てる場所（SSEなど）で、初回のCookieを付け直す。

    FastAPIは、応答オブジェクトを直接返す場合に
    差し込んだResponseのCookieを引き継がない。付け忘れると、
    つなぎ直すたびに別人扱いになり履歴が分かれてしまうため、ここで明示的に付ける。
    """

    new_user_id = getattr(request.state, "new_user_id", None)
    if new_user_id:
        _set_user_cookie(response, new_user_id)
    return response


def current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    toyocho_user: str | None = Cookie(default=None),
) -> str:
    """利用者を特定する。初めての端末なら自動で作る（登録不要で使えるようにするため）。

    新しく作った場合は`request.state`にも控えておく。
    StreamingResponse（SSE）のように応答を自分で組み立てる場所では、
    ここで設定したCookieが引き継がれないため、呼び出し側で付け直せるようにしている。
    """

    request.state.new_user_id = None
    if toyocho_user and db.get(store.UserRow, toyocho_user) is not None:
        return toyocho_user

    user = store.create_user(db)
    request.state.new_user_id = user.id
    _set_user_cookie(response, user.id)
    return user.id


# ---- 入出力の形 ----


class SubscriptionIn(BaseModel):
    line_id: str
    station_id: str
    direction: str | None = None
    destination: str | None = None
    train_number: str | None = None
    notify_on: list[str] = Field(default_factory=lambda: sorted(NOTIFY_DEFAULT))


class SubscriptionOut(BaseModel):
    id: str
    line_id: str
    line_name: str
    station_id: str
    direction: str | None
    destination: str | None
    train_number: str | None
    notify_on: list[str]
    active: bool


class AlertOut(BaseModel):
    id: str
    line_name: str
    station_id: str
    destination: str
    train_number: str
    kind: str
    delay_minutes: int
    fired_at: datetime
    acked_at: datetime | None


def _to_out(row: store.SubscriptionRow) -> SubscriptionOut:
    line = metro.get_line(row.line_id)
    return SubscriptionOut(
        id=row.id,
        line_id=row.line_id,
        line_name=line.name if line else row.line_id,
        station_id=row.station_id,
        direction=row.direction,
        destination=row.destination,
        train_number=row.train_number,
        notify_on=row.notify_on.split(",") if row.notify_on else [],
        active=row.active,
    )


# ---- 路線・駅 ----


@app.get("/api/lines")
def get_lines() -> list[dict]:
    """東京メトロの全路線と駅。めったに変わらないため画面側で保存してよい。"""

    return [
        {
            "id": line.id,
            "name": line.name,
            "color": line.color,
            "directions": list(line.directions),
            "stations": list(line.stations),
        }
        for line in metro.LINES
    ]


# ---- 購読 ----


@app.get("/api/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(
    user_id: str = Depends(current_user), db: Session = Depends(get_db)
) -> list[SubscriptionOut]:
    rows = db.scalars(
        select(store.SubscriptionRow)
        .where(store.SubscriptionRow.user_id == user_id)
        .order_by(store.SubscriptionRow.created_at.desc())
    ).all()
    return [_to_out(row) for row in rows]


@app.post("/api/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    body: SubscriptionIn,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    line = metro.get_line(body.line_id)
    if line is None:
        raise HTTPException(400, "その路線は取り扱っていません。")
    if body.station_id not in line.stations:
        raise HTTPException(400, f"{line.name}に「{body.station_id}」駅はありません。")
    if body.direction is not None and body.direction not in line.directions:
        raise HTTPException(400, "方面の指定が正しくありません。")
    if not body.notify_on:
        raise HTTPException(400, "通知のタイミングを1つ以上選んでください。")

    row = store.SubscriptionRow(
        user_id=user_id,
        line_id=body.line_id,
        station_id=body.station_id,
        direction=body.direction,
        destination=body.destination,
        train_number=body.train_number,
        notify_on=",".join(sorted(set(body.notify_on))),
    )
    db.add(row)
    db.commit()
    service.reload_subscriptions()
    return _to_out(row)


@app.patch("/api/subscriptions/{subscription_id}", response_model=SubscriptionOut)
def toggle_subscription(
    subscription_id: str,
    active: bool,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    row = db.get(store.SubscriptionRow, subscription_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "見張りの設定が見つかりません。")
    row.active = active
    db.commit()
    service.reload_subscriptions()
    return _to_out(row)


@app.delete("/api/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: str,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(store.SubscriptionRow, subscription_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "見張りの設定が見つかりません。")
    db.delete(row)
    db.commit()
    service.reload_subscriptions()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- 通知の受け取り先 ----


class PushIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


@app.get("/api/push/key")
def push_key() -> dict:
    return {"public_key": VAPID_PUBLIC_KEY, "enabled": bool(VAPID_PUBLIC_KEY)}


@app.post("/api/push/register", status_code=201)
def register_push(
    body: PushIn,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(store.DeviceRow).where(store.DeviceRow.endpoint == body.endpoint)
    )
    if existing is not None:
        existing.user_id = user_id
        existing.p256dh = body.p256dh
        existing.auth = body.auth
        existing.revoked_at = None
    else:
        db.add(
            store.DeviceRow(
                user_id=user_id,
                endpoint=body.endpoint,
                p256dh=body.p256dh,
                auth=body.auth,
            )
        )
    db.commit()
    return {"ok": True}


# ---- 履歴 ----


@app.get("/api/alerts", response_model=list[AlertOut])
def list_alerts(
    limit: int = 50,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    rows = db.scalars(
        select(store.AlertRow)
        .where(store.AlertRow.user_id == user_id)
        .order_by(store.AlertRow.fired_at.desc())
        .limit(min(limit, 200))
    ).all()
    return [
        AlertOut(
            id=r.id,
            line_name=(metro.get_line(r.line_id).name if metro.get_line(r.line_id) else r.line_id),
            station_id=r.station_id,
            destination=r.destination,
            train_number=r.train_number,
            kind=r.kind,
            delay_minutes=r.delay_minutes,
            fired_at=r.fired_at,
            acked_at=r.acked_at,
        )
        for r in rows
    ]


@app.post("/api/alerts/{alert_id}/ack", status_code=204)
def ack_alert(
    alert_id: str,
    user_id: str = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(store.AlertRow, alert_id)
    if row is not None and row.user_id == user_id and row.acked_at is None:
        row.acked_at = store.now_utc()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- 実時間の配信（SSE） ----


@app.get("/api/stream")
async def stream(request: Request, user_id: str = Depends(current_user)):
    """画面を開いている間、通知をすぐ届ける通り道。"""

    queue = service.live.connect(user_id)

    async def events():
        yield ": connected\n\n"
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # 途中の機器に切られないようにする
        finally:
            service.live.disconnect(user_id, queue)

    return attach_new_user_cookie(
        request,
        StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        ),
    )


# ---- 状態確認 ----


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "watched_lines": service.watched_lines(),
        "subscriptions": len(service.index),
        "live_connections": service.live.connection_count(),
        "push_enabled": service.push.enabled,
        **service.stats,
    }


# ---- 画面（PWA） ----

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        # サービスワーカーは、置き場所より上の範囲を扱えないため最上位で返す
        return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")

    @app.get("/manifest.json")
    def manifest() -> FileResponse:
        return FileResponse(WEB_DIR / "manifest.json", media_type="application/json")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")
