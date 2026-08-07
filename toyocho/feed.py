"""上流（東京メトロの列車位置）からの取得（Ver2）。

対象は東京メトロのみのため、取り込み先は1種類だけ。
他社対応のための抽象化は入れない（社長指示、2026-08-07。単純さを優先）。
自動テストでは`FakeFeed`を使い、本物の通信は行わない。

速さと負荷のための工夫：
- `update`（上流の更新時刻）が前回と同じなら、以降の処理を丸ごと省く
- 見張っている人がいない路線は、そもそも取りに行かない（呼び出し側で判断）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .domain import LineSnapshot, TrainSnapshot

FEED_URL = "https://nkth.info/traffic_info/ODPT/now"
TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class FeedResult:
    """取り込み1回ぶんの結果。"""

    snapshot: LineSnapshot
    version: int  # 上流の更新時刻（ミリ秒）。同じなら中身も同じ


def parse(line_id: str, payload: dict) -> FeedResult:
    """上流の応答を、この製品の形（LineSnapshot）に直す。

    上流の`now`は在線駅の一覧で、1駅なら在線・2駅ならその区間を走行中を表す。
    """

    version = int(payload.get("update") or 0)
    observed_at = (
        datetime.fromtimestamp(version / 1000, tz=timezone.utc).replace(tzinfo=None)
        if version
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )

    trains: list[TrainSnapshot] = []
    for raw in list(payload.get("noRunning") or []) + list(payload.get("running") or []):
        number = raw.get("number") or raw.get("ODPTnumber")
        if not number:
            continue
        trains.append(
            TrainSnapshot(
                line_id=line_id,
                train_number=str(number),
                destination=str(raw.get("destination") or ""),
                current_stations=frozenset(raw.get("now") or ()),
                direction=raw.get("direction_text") or None,
                delay_minutes=int(raw.get("delay_value") or 0),
            )
        )

    return FeedResult(
        snapshot=LineSnapshot(
            line_id=line_id, observed_at=observed_at, trains=tuple(trains)
        ),
        version=version,
    )


class MetroFeed:
    """本物の上流から取ってくる実装。"""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        self._owns_client = client is None

    async def fetch(self, line_id: str) -> FeedResult:
        response = await self._client.get(FEED_URL, params={"line": line_id})
        response.raise_for_status()
        return parse(line_id, response.json())

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
