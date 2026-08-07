"""通知の配信（Ver2）。

状態によって経路を変える二層構成にしている。

- 画面を開いている人 → **SSE**（つなぎっぱなしの通信）で即時。音と振動もすぐ鳴る
- 画面を閉じている人 → **Web Push**（携帯のOSに届く通知）

どちらか一方では商用に足りない。SSEは速いが画面を閉じると切れ、
Web Pushは確実だが数秒かかるため、両方を併用する。

Web Pushの鍵（VAPID）が未設定でも、SSEだけで動く（開発中に困らないようにするため）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")


@dataclass(frozen=True)
class AlertPayload:
    """画面と通知に渡す中身。"""

    alert_id: str
    line_id: str
    line_name: str
    station: str
    destination: str
    direction: str | None
    train_number: str
    kind: str  # approaching（接近）/ arrived（到着）
    delay_minutes: int
    fired_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class LiveConnections:
    """SSEでつながっている画面の一覧（利用者ごと）。

    1人が複数の端末・タブで開いていても、すべてに同じ内容を送る。
    """

    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue[str]]] = {}

    def connect(self, user_id: str) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._queues.setdefault(user_id, set()).add(queue)
        return queue

    def disconnect(self, user_id: str, queue: asyncio.Queue[str]) -> None:
        bucket = self._queues.get(user_id)
        if not bucket:
            return
        bucket.discard(queue)
        if not bucket:
            del self._queues[user_id]

    def send(self, user_id: str, payload: AlertPayload) -> int:
        """つながっている画面すべてへ送る。送れた数を返す。"""

        message = payload.to_json()
        sent = 0
        for queue in list(self._queues.get(user_id, ())):
            try:
                queue.put_nowait(message)
                sent += 1
            except asyncio.QueueFull:
                # 受け取りが追いつかない画面は捨てる（他の人の通知を遅らせないため）
                logger.warning("SSE: 送信待ちが詰まったため1件破棄しました（%s）", user_id)
        return sent

    def connection_count(self) -> int:
        return sum(len(v) for v in self._queues.values())


class WebPushSender:
    """携帯のOSに通知を出す（画面を閉じていても届く）。"""

    def __init__(self) -> None:
        self.enabled = bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)
        if not self.enabled:
            logger.info(
                "Web Push: 鍵（VAPID）が未設定のため、OS通知は送りません"
                "（画面を開いている間の通知だけ動きます）。"
            )

    def send(self, endpoint: str, p256dh: str, auth: str, payload: AlertPayload) -> bool:
        if not self.enabled:
            return False
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {"p256dh": p256dh, "auth": auth},
                },
                data=payload.to_json(),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=120,  # 2分で無効。古い接近通知は届いても意味がないため
            )
            return True
        except WebPushException as error:
            status = getattr(error.response, "status_code", None)
            if status in (404, 410):
                logger.info("Web Push: 送り先が無効になっていました（削除対象）")
                raise DeviceGone(endpoint) from error
            logger.warning("Web Push: 送信に失敗しました（%s）", status)
            return False
        except Exception:  # noqa: BLE001 - 通知の失敗で全体を止めない
            logger.exception("Web Push: 想定外のエラー")
            return False


class DeviceGone(Exception):
    """送り先が無効（端末の通知許可が取り消された等）。登録を消す合図。"""

    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        self.endpoint = endpoint


def build_payload(alert_id: str, event, line_name: str, fired_at: datetime) -> AlertPayload:
    return AlertPayload(
        alert_id=alert_id,
        line_id=event.line_id,
        line_name=line_name,
        station=getattr(event, "station_id", ""),
        destination=getattr(event, "destination", ""),
        direction=getattr(event, "direction", None),
        train_number=event.train_number,
        kind=getattr(event, "kind", "arrived"),
        delay_minutes=getattr(event, "delay_minutes", 0),
        fired_at=fired_at.isoformat(timespec="seconds"),
    )
