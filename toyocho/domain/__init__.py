"""TOYOCHO ALERT Ver2 の判定の中核（外部依存ゼロの層）。

この層は、通信・データベース・現在時刻の取得を**一切行わない**。
そのため、通信もデータベースも用意せずに、すべての判定を自動テストできる。

使う側（取り込みワーカー・API）は、この層の関数へデータと現在時刻を渡すだけでよい。
"""

from .dedupe import DEFAULT_TTL_SECONDS, DedupeStore, InMemoryDedupeStore, dedupe_key
from .diffing import diff_snapshots
from .events import (
    NOTIFY_APPROACHING,
    NOTIFY_ARRIVED,
    AlertableEvent,
    DelayChanged,
    TrainApproaching,
    TrainArrived,
    TrainDeparted,
    TrainEvent,
)
from .index import SubscriptionIndex
from .matching import find_matches, matches
from .models import (
    ALWAYS,
    NOTIFY_DEFAULT,
    ActiveSchedule,
    LineSnapshot,
    Subscription,
    TrainSnapshot,
)

__all__ = [
    "ALWAYS",
    "ActiveSchedule",
    "AlertableEvent",
    "DEFAULT_TTL_SECONDS",
    "DedupeStore",
    "DelayChanged",
    "InMemoryDedupeStore",
    "LineSnapshot",
    "NOTIFY_APPROACHING",
    "NOTIFY_ARRIVED",
    "NOTIFY_DEFAULT",
    "Subscription",
    "SubscriptionIndex",
    "TrainApproaching",
    "TrainArrived",
    "TrainDeparted",
    "TrainEvent",
    "TrainSnapshot",
    "dedupe_key",
    "diff_snapshots",
    "find_matches",
    "matches",
]
