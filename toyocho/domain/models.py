"""列車・駅・購読を表すデータ（Ver2 Phase1）。

ここは**外部に一切依存しない層**（domain層）。
HTTP・データベース・現在時刻の取得を行わない。時刻は必ず引数で受け取る。

そうする理由：
- 判定の正しさを、通信もデータベースも使わずに自動テストで確かめられる
- 路線が増えても、通知手段が変わっても、この層は書き換えなくてよい

すべて`frozen=True`（作った後は変えられない）にしてある。
Ver1の不具合の多くは「1つの辞書を複数箇所から書き換えていた」ことが原因のため、
書き換えられない形にして、同じ問題が起きないようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time

from .events import NOTIFY_APPROACHING, NOTIFY_ARRIVED


@dataclass(frozen=True)
class TrainSnapshot:
    """ある時点での列車1本の状態（上流データ1件ぶん）。"""

    line_id: str
    train_number: str  # 列番（例：A1234S）
    destination: str  # 行先（例：西船橋）
    current_stations: frozenset[str] = frozenset()  # いま在線している駅
    direction: str | None = None  # 上り／下り（上流にない場合はNone）
    delay_minutes: int = 0

    def is_at(self, station_id: str) -> bool:
        return station_id in self.current_stations


@dataclass(frozen=True)
class LineSnapshot:
    """ある時点での路線1本ぶんの状態（取り込み1回ぶん）。"""

    line_id: str
    observed_at: datetime
    trains: tuple[TrainSnapshot, ...] = ()

    def by_train_number(self) -> dict[str, TrainSnapshot]:
        return {t.train_number: t for t in self.trains}


@dataclass(frozen=True)
class ActiveSchedule:
    """購読を有効にする曜日・時間帯。

    - `weekdays`がNoneなら毎日。0=月曜〜6=日曜。
    - `start`／`end`がどちらもNoneなら終日。
    - `start`より`end`が小さい場合は**日をまたぐ**帯とみなす（例：22:00〜06:00）。
      「夜だけ鳴らさない」等をこの1つの型で表せるようにするため。
    """

    weekdays: frozenset[int] | None = None
    start: time | None = None
    end: time | None = None

    def is_active_at(self, now: datetime) -> bool:
        if self.weekdays is not None and now.weekday() not in self.weekdays:
            return False
        if self.start is None and self.end is None:
            return True

        current = now.time()
        start = self.start or time.min
        end = self.end or time.max

        if start <= end:
            return start <= current < end
        # 日をまたぐ帯（例：22:00〜06:00）
        return current >= start or current < end


ALWAYS = ActiveSchedule()

# 既定は「接近・到着のどちらでも」。
# 重複排除が同じ列車・同じ駅を1回にまとめるため、
# 実際には**先に届いたほう（＝速いほう）だけ**が鳴る。二度は鳴らない。
NOTIFY_DEFAULT = frozenset({NOTIFY_APPROACHING, NOTIFY_ARRIVED})


@dataclass(frozen=True)
class Subscription:
    """利用者1人ぶんの「見張り」の設定。

    Ver1では監視条件がサーバー全体で1組しか持てなかった（＝1人しか使えなかった）。
    Ver2ではこれを**利用者ごとの実体**にすることで、複数利用者・複数路線を成立させる。

    絞り込み項目（`direction`／`destination`／`train_number`）は、
    Noneなら「指定なし＝すべて対象」を意味する。
    """

    id: str
    user_id: str
    line_id: str
    station_id: str
    direction: str | None = None
    destination: str | None = None
    train_number: str | None = None
    lead_time_sec: int = 0  # 何秒前に鳴らすか（将来のAI予測で使う）
    schedule: ActiveSchedule = field(default=ALWAYS)
    notify_on: frozenset[str] = field(default=NOTIFY_DEFAULT)
    active: bool = True
