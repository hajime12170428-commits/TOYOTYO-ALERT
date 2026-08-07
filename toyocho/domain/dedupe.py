"""重複排除（Ver2 Phase1）。同じ列車で二度鳴らさないための最後の砦。

差分方式（diffing.py）で二重通知は原理的に起きないが、
現実には次の場合に「同じ到着」が二度届きうる：

- サーバーを再起動して、前回の状態を失ったとき
- 取り込みを二重に動かしてしまったとき
- 上流データが一時的に前後したとき

そこで「この購読×この列車×この駅は、もう鳴らした」を期限つきで覚えておく。
本番ではRedisに置き換える（同じ`DedupeStore`の形のまま差し替えられる）。
現在時刻は外から渡す作りにしてあるため、期限切れの動きも自動テストできる。
"""

from __future__ import annotations

from typing import Callable, Protocol

from .events import TrainEvent
from .models import Subscription

DEFAULT_TTL_SECONDS = 900  # 15分


def dedupe_key(sub: Subscription, event: TrainEvent) -> str:
    """重複排除のかぎ。購読・列車・駅の組み合わせで一意にする。"""

    station_id = getattr(event, "station_id", "")
    return f"alert:{sub.id}:{event.train_number}:{station_id}"


class DedupeStore(Protocol):
    """重複排除の置き場所（メモリ／Redisを差し替えるための窓口）。"""

    def acquire(self, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        """初めてなら覚えてTrueを返す。すでに覚えていればFalse（＝鳴らさない）。"""
        ...


class InMemoryDedupeStore:
    """1台構成・自動テスト用の実装。時計は外から渡す。"""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._expires_at: dict[str, float] = {}

    def acquire(self, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        now = self._clock()
        expires = self._expires_at.get(key)
        if expires is not None and expires > now:
            return False
        self._expires_at[key] = now + ttl_seconds
        return True

    def purge_expired(self) -> int:
        now = self._clock()
        expired = [k for k, v in self._expires_at.items() if v <= now]
        for key in expired:
            del self._expires_at[key]
        return len(expired)
