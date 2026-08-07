"""取り込み→判定→配信をつなぐ中心（Ver2）。

ここがVer2の心臓部。Ver1との決定的な違いは、
**上流への問い合わせが利用者数と無関係**なこと。

  Ver1：利用者1人につき1本の見張りスレッド＝1万人なら毎秒5,000リクエスト
  Ver2：路線ごとに1本だけ取り込み、全購読へ配る＝毎秒10リクエスト以下

処理の流れ（路線1本ぶん・1回の巡回）：
  1. 見張っている人がいる路線だけ、上流から取ってくる
  2. 上流の更新時刻が前回と同じなら、そこで終わり（無駄な処理をしない）
  3. 前回との差分から「接近／到着」の出来事を作る
  4. 索引で関係する購読だけを引き当て、条件を判定する
  5. 重複排除を通ったものだけ、記録して配信する
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from . import metro, store
from .domain import (
    InMemoryDedupeStore,
    LineSnapshot,
    SubscriptionIndex,
    dedupe_key,
    diff_snapshots,
    find_matches,
)
from .domain.events import TrainApproaching, TrainArrived
from .notify import AlertPayload, DeviceGone, LiveConnections, WebPushSender, build_payload

logger = logging.getLogger(__name__)

# 巡回の間隔（秒）。上流は約2秒ごとに更新される（2026-08-07に実測）ため、
# これより短くしても新しい情報は得られない。
POLL_INTERVAL_SECONDS = 2.0
# 誰も見張っていないときの待ち時間（無駄な処理をしない）
IDLE_INTERVAL_SECONDS = 15.0
# 重複排除の古い記録を片づける間隔（巡回の回数）。
# 片づけないと、記録が増え続けてメモリを圧迫する。
CLEANUP_EVERY_POLLS = 300  # 2秒間隔なら約10分ごと


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AlertService:
    """購読の索引を持ち、出来事を通知に変える。"""

    def __init__(
        self,
        live: LiveConnections | None = None,
        push: WebPushSender | None = None,
    ) -> None:
        self.index = SubscriptionIndex()
        self.live = live or LiveConnections()
        self.push = push or WebPushSender()
        self.dedupe = InMemoryDedupeStore(time.monotonic)
        self._snapshots: dict[str, LineSnapshot] = {}
        self._versions: dict[str, int] = {}
        self.stats = {"polls": 0, "skipped_unchanged": 0, "events": 0, "alerts": 0}

    # ---- 購読の索引 ----

    def reload_subscriptions(self) -> int:
        """データベースから読み直して索引を作り直す（起動時・購読の変更時）。"""

        with store.get_session() as db:
            subs = store.load_active_subscriptions(db)
        self.index = SubscriptionIndex(subs)
        logger.info("購読の索引を更新しました（%d件）。", len(self.index))
        return len(self.index)

    def watched_lines(self) -> list[str]:
        """いま誰かが見張っている路線だけを返す（＝取りに行く必要がある路線）。"""

        return sorted(self.index.watched_lines())

    # ---- 出来事の処理 ----

    def handle_snapshot(self, result) -> int:
        """取り込み1回ぶんを処理して、鳴らした件数を返す。"""

        line_id = result.snapshot.line_id
        self.stats["polls"] += 1

        # 上流が更新されていなければ、以降を丸ごと省く
        if result.version and self._versions.get(line_id) == result.version:
            self.stats["skipped_unchanged"] += 1
            return 0
        self._versions[line_id] = result.version

        events = diff_snapshots(self._snapshots.get(line_id), result.snapshot)
        self._snapshots[line_id] = result.snapshot
        self.stats["events"] += len(events)

        now = _now()
        fired = 0
        for event in events:
            if not isinstance(event, (TrainApproaching, TrainArrived)):
                continue
            候補 = self.index.candidates_for(event)
            if not 候補:
                continue
            for sub in find_matches(候補, event, now):
                if not self.dedupe.acquire(dedupe_key(sub, event)):
                    continue  # 同じ列車・同じ駅では二度鳴らさない
                self._deliver(sub, event, now)
                fired += 1

        self.stats["alerts"] += fired
        return fired

    def _deliver(self, sub, event, now: datetime) -> None:
        line = metro.get_line(event.line_id)
        line_name = line.name if line else event.line_id

        with store.get_session() as db:
            row = store.record_alert(db, sub, event, event.kind)
            payload = build_payload(row.id, event, line_name, now)
            self.live.send(sub.user_id, payload)
            self._push_to_devices(db, sub.user_id, payload)

        logger.info(
            "通知：%s %s駅 %s行 %s（%s）",
            line_name,
            payload.station,
            payload.destination,
            payload.train_number,
            "接近" if payload.kind == "approaching" else "到着",
        )

    def _push_to_devices(self, db, user_id: str, payload: AlertPayload) -> None:
        if not self.push.enabled:
            return
        devices = db.scalars(
            select(store.DeviceRow).where(
                store.DeviceRow.user_id == user_id,
                store.DeviceRow.revoked_at.is_(None),
            )
        ).all()
        for device in devices:
            try:
                self.push.send(device.endpoint, device.p256dh, device.auth, payload)
            except DeviceGone:
                device.revoked_at = _now()
                db.commit()


class Poller:
    """路線ごとの巡回。誰も見張っていない路線には問い合わせない。"""

    def __init__(self, service: AlertService, feed) -> None:
        self.service = service
        self.feed = feed
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self) -> int:
        lines = self.service.watched_lines()
        if not lines:
            return 0

        results = await asyncio.gather(
            *(self.feed.fetch(line_id) for line_id in lines), return_exceptions=True
        )
        fired = 0
        for line_id, result in zip(lines, results):
            if isinstance(result, Exception):
                logger.warning("取り込み失敗（%s）：%s", line_id, result)
                continue
            try:
                fired += self.service.handle_snapshot(result)
            except Exception:  # noqa: BLE001 - 1路線の失敗で他を止めない
                logger.exception("処理中のエラー（%s）", line_id)
        return fired

    async def _loop(self) -> None:
        polls_since_cleanup = 0
        while not self._stop.is_set():
            try:
                await self.run_once()
                polls_since_cleanup += 1
                if polls_since_cleanup >= CLEANUP_EVERY_POLLS:
                    removed = self.service.dedupe.purge_expired()
                    polls_since_cleanup = 0
                    if removed:
                        logger.debug("重複排除の古い記録を%d件片づけました。", removed)
            except Exception:  # noqa: BLE001 - 巡回は止めない
                logger.exception("巡回中の想定外のエラー（次回に再挑戦します）")
            interval = (
                POLL_INTERVAL_SECONDS
                if self.service.watched_lines()
                else IDLE_INTERVAL_SECONDS
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="metro-poller")
            logger.info("巡回を開始しました（%.1f秒ごと）。", POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
