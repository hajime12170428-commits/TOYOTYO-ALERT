"""列車の「出来事」（Ver2）。

Ver1は「いま駅にいる列車の一覧」を2秒ごとに見て鳴らしていたため、
列車が駅に停まっている間ずっと条件に一致し続けた。
Ver1はこれを`notified_trains`というメモリ上の集合で後から打ち消していたが、
サーバーを再起動すると集合が消えるため、**同じ列車でまた鳴る**問題が残っていた。

Ver2は「状態」ではなく**前回との差分＝出来事**で考える。
「到着した」という出来事は1回しか起きないため、二重通知が設計上起こらない。

上流データの`now`（在線）は次の2通りを表す（実データで確認済み）：
- 1駅だけ（例：["落合"]）      → その駅に在線している＝**到着**
- 2駅（例：["中野","落合"]）   → その2駅の**間を走行中**

そこで、前回いなかった駅が「駅間」として現れた時点を**接近**として扱う。
到着を待たずに鳴らせるため、通知が実質1駅ぶん早くなる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# 購読が「どの時点で鳴らすか」の指定に使う名前
NOTIFY_APPROACHING = "approaching"
NOTIFY_ARRIVED = "arrived"


@dataclass(frozen=True)
class TrainEvent:
    """すべての出来事に共通する項目。"""

    line_id: str
    train_number: str
    occurred_at: datetime


@dataclass(frozen=True)
class TrainApproaching(TrainEvent):
    """列車がその駅へ向かって走行中（駅間）。到着より早い＝通知が速い。"""

    station_id: str = ""
    destination: str = ""
    direction: str | None = None
    delay_minutes: int = 0

    kind: str = NOTIFY_APPROACHING


@dataclass(frozen=True)
class TrainArrived(TrainEvent):
    """列車が駅に在線した。"""

    station_id: str = ""
    destination: str = ""
    direction: str | None = None
    delay_minutes: int = 0

    kind: str = NOTIFY_ARRIVED


@dataclass(frozen=True)
class TrainDeparted(TrainEvent):
    """列車が駅から離れた（次に来たときに再び鳴らせるようにするための出来事）。"""

    station_id: str = ""


@dataclass(frozen=True)
class DelayChanged(TrainEvent):
    """遅れの分数が変わった（将来の遅延通知・AI学習で使う）。"""

    previous_minutes: int = 0
    current_minutes: int = 0


# 通知の対象になりうる出来事
AlertableEvent = TrainApproaching | TrainArrived
