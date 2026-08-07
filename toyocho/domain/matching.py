"""出来事と購読の一致判定（Ver2）。

「誰に鳴らすべきか」の判断は、すべてこの1ファイルに集める。
外部依存ゼロ・現在時刻は引数で受け取るため、時間帯の条件も自動テストできる。
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .events import TrainApproaching, TrainArrived, TrainEvent
from .models import Subscription


def matches(sub: Subscription, event: TrainEvent, now: datetime) -> bool:
    """この購読が、この出来事で鳴るべきかを返す。

    絞り込み項目がNoneのときは「指定なし＝すべて対象」として扱う。
    """

    if not sub.active:
        return False
    if not isinstance(event, (TrainApproaching, TrainArrived)):
        return False  # 出発・遅延変化では鳴らさない
    if event.kind not in sub.notify_on:
        return False
    if sub.line_id != event.line_id:
        return False
    if sub.station_id != event.station_id:
        return False
    if sub.destination is not None and sub.destination != event.destination:
        return False
    if sub.train_number is not None and sub.train_number != event.train_number:
        return False
    if sub.direction is not None and sub.direction != event.direction:
        return False
    if not sub.schedule.is_active_at(now):
        return False
    return True


def find_matches(
    subs: Sequence[Subscription], event: TrainEvent, now: datetime
) -> list[Subscription]:
    """出来事に一致する購読をすべて返す。"""

    return [sub for sub in subs if matches(sub, event, now)]
