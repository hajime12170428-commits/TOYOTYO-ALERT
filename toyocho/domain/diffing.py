"""前回と今回の差分から「出来事」を作る（Ver2の中核）。

この関数が、Ver1の二重通知問題を**構造的に**解決する部分。
外部依存ゼロ・状態を持たない純粋な関数のため、
通信もデータベースも使わずに全パターンを自動テストできる。

在線の読み方（上流データで確認済み）：
- `now`が1駅   → その駅に**在線**している
- `now`が2駅   → その2駅の**間を走行中**（前回いなかった側の駅へ**接近**中）
"""

from __future__ import annotations

from .events import (
    DelayChanged,
    TrainApproaching,
    TrainArrived,
    TrainDeparted,
    TrainEvent,
)
from .models import LineSnapshot, TrainSnapshot


def _at_station(train: TrainSnapshot | None) -> str | None:
    """在線している駅（1駅のときだけ）。走行中・不明ならNone。"""

    if train is None:
        return None
    if len(train.current_stations) != 1:
        return None
    return next(iter(train.current_stations))


def diff_snapshots(
    previous: LineSnapshot | None,
    current: LineSnapshot,
    *,
    emit_initial_arrivals: bool = False,
) -> list[TrainEvent]:
    """前回の状態と今回の状態を比べて、起きた出来事の一覧を返す。

    - 接近：前回いなかった駅へ向かって走行中になった（駅間）
    - 到着：在線している駅が変わった
    - 出発：在線していた駅から離れた
    - 遅延変化：遅れの分数が変わった

    `emit_initial_arrivals`（初回の扱い）：
        初回（previous=None）は既定で**何も出さない**。
        サーバーを起動した瞬間に、たまたま駅に停まっている列車で
        いっせいに鳴ってしまうのを防ぐため（Ver1で起きていた挙動）。
    """

    if previous is None:
        if not emit_initial_arrivals:
            return []
        previous = LineSnapshot(line_id=current.line_id, observed_at=current.observed_at)

    events: list[TrainEvent] = []
    before = previous.by_train_number()
    after = current.by_train_number()
    at = current.observed_at

    for train_number, now_train in after.items():
        was = before.get(train_number)
        previous_stations = was.current_stations if was else frozenset()
        was_at = _at_station(was)
        now_at = _at_station(now_train)

        # 接近（駅間）：前回いなかった駅が、走行中の区間に現れた
        if now_at is None:
            for station_id in sorted(now_train.current_stations - previous_stations):
                events.append(
                    TrainApproaching(
                        line_id=current.line_id,
                        train_number=train_number,
                        occurred_at=at,
                        station_id=station_id,
                        destination=now_train.destination,
                        direction=now_train.direction,
                        delay_minutes=now_train.delay_minutes,
                    )
                )

        # 到着：在線している駅が変わった（停まり続けている間は再度出さない）
        if now_at is not None and now_at != was_at:
            events.append(
                TrainArrived(
                    line_id=current.line_id,
                    train_number=train_number,
                    occurred_at=at,
                    station_id=now_at,
                    destination=now_train.destination,
                    direction=now_train.direction,
                    delay_minutes=now_train.delay_minutes,
                )
            )

        # 出発：在線していた駅から離れた
        if was_at is not None and was_at != now_at:
            events.append(
                TrainDeparted(
                    line_id=current.line_id,
                    train_number=train_number,
                    occurred_at=at,
                    station_id=was_at,
                )
            )

        if was is not None and was.delay_minutes != now_train.delay_minutes:
            events.append(
                DelayChanged(
                    line_id=current.line_id,
                    train_number=train_number,
                    occurred_at=at,
                    previous_minutes=was.delay_minutes,
                    current_minutes=now_train.delay_minutes,
                )
            )

    # 一覧から消えた列車（運転終了・区間外へ）は、在線していた駅から出発したとみなす。
    for train_number, was in before.items():
        if train_number in after:
            continue
        was_at = _at_station(was)
        if was_at is not None:
            events.append(
                TrainDeparted(
                    line_id=current.line_id,
                    train_number=train_number,
                    occurred_at=at,
                    station_id=was_at,
                )
            )

    return events
