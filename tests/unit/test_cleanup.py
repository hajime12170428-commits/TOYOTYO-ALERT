"""重複排除の記録が増え続けないことの確認（Ver2）。

長時間動かし続けても、メモリを圧迫しないための守り。
"""

from __future__ import annotations

from toyocho.domain import InMemoryDedupeStore


class 手動時計:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_期限切れの記録は片づけられる():
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)

    for i in range(1000):
        store.acquire(f"alert:s{i}:A1:木場", ttl_seconds=900)
    assert len(store._expires_at) == 1000

    clock.now = 901  # 15分経過
    removed = store.purge_expired()

    assert removed == 1000
    assert len(store._expires_at) == 0


def test_まだ有効な記録は残る():
    clock = 手動時計()
    store = InMemoryDedupeStore(clock)
    store.acquire("古い", ttl_seconds=100)
    clock.now = 50
    store.acquire("新しい", ttl_seconds=100)

    clock.now = 101  # 「古い」だけ期限切れ
    removed = store.purge_expired()

    assert removed == 1
    assert store.acquire("新しい") is False  # まだ覚えている＝二度鳴らさない
