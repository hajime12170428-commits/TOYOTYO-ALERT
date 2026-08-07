"""購読の索引（Ver2 Phase1）。数万人対応の要。

Ver1は利用者が増えるほど処理が重くなる作りだった。
Ver2は「路線＋駅」をかぎにした索引を持ち、出来事1件あたり**一発で引き当てる**。
購読が10件でも10万件でも、引き当てにかかる時間はほぼ変わらない。

この構造体は外部依存ゼロ（データベースもRedisも使わない）。
実際の運用では、データベースから読み出してこの索引を組み立て、
購読が変わったときだけ作り直す。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .events import TrainEvent
from .models import Subscription


class SubscriptionIndex:
    """(路線, 駅) → 購読の一覧。参照は一定時間（O(1)）。"""

    def __init__(self, subscriptions: Iterable[Subscription] = ()) -> None:
        self._by_station: dict[tuple[str, str], list[Subscription]] = defaultdict(list)
        self._by_id: dict[str, Subscription] = {}
        for sub in subscriptions:
            self.add(sub)

    def add(self, sub: Subscription) -> None:
        if sub.id in self._by_id:
            self.remove(sub.id)
        self._by_id[sub.id] = sub
        if sub.active:
            self._by_station[(sub.line_id, sub.station_id)].append(sub)

    def remove(self, subscription_id: str) -> None:
        sub = self._by_id.pop(subscription_id, None)
        if sub is None:
            return
        key = (sub.line_id, sub.station_id)
        bucket = self._by_station.get(key)
        if not bucket:
            return
        self._by_station[key] = [s for s in bucket if s.id != subscription_id]
        if not self._by_station[key]:
            del self._by_station[key]

    def find(self, line_id: str, station_id: str) -> list[Subscription]:
        return self._by_station.get((line_id, station_id), [])

    def candidates_for(self, event: TrainEvent) -> list[Subscription]:
        """出来事に関係しうる購読だけを返す（細かい条件はmatchingが判定する）。"""

        station_id = getattr(event, "station_id", None)
        if station_id is None:
            return []
        return self.find(event.line_id, station_id)

    def watched_lines(self) -> set[str]:
        """いま誰かが見張っている路線。取り込みが必要な路線を決めるのに使う
        （＝購読ゼロの路線は上流に問い合わせない＝無駄な費用と負荷を出さない）。"""

        return {line_id for line_id, _ in self._by_station}

    def __len__(self) -> int:
        return sum(len(bucket) for bucket in self._by_station.values())
