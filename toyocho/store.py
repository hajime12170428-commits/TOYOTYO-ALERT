"""保存（Ver2）。購読・端末・通知履歴をデータベースに置く。

路線と駅は変わらないデータなのでコード（metro.py）に持ち、ここでは扱わない。
接続先は環境変数`DATABASE_URL`で切り替える（標準はこのフォルダーのSQLite）。
そのままPostgreSQLへ移せるが、東京メトロ規模ではSQLiteでも十分動く。

**通知の判定はこの層を通らない**（判定はメモリ上の索引で行う）。
データベースが遅くても、通知の速さには影響しない作りにしている。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .domain import ActiveSchedule, Subscription
from .domain.models import NOTIFY_DEFAULT

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "toyocho.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")


def now_utc() -> datetime:
    """保存に使う現在時刻（世界標準時・タイムゾーン情報なし）。

    表示は画面側で日本時間に直す。保存を世界標準時にそろえておくと、
    夏時間や端末の設定に左右されない。
    """

    return datetime.now(timezone.utc).replace(tzinfo=None)


_now = now_utc  # 内部で使う短い別名


def _new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """利用者。登録不要で使えるよう、端末ごとに自動で作る。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DeviceRow(Base):
    """通知の送り先（1人が複数の端末を持てる）。"""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubscriptionRow(Base):
    """見張りの設定（利用者ごと・路線ごと）。"""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    line_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(64), nullable=True)
    train_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notify_on: Mapped[str] = mapped_column(String(64), default="approaching,arrived")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def to_domain(self) -> Subscription:
        return Subscription(
            id=self.id,
            user_id=self.user_id,
            line_id=self.line_id,
            station_id=self.station_id,
            direction=self.direction,
            destination=self.destination,
            train_number=self.train_number,
            schedule=ActiveSchedule(),
            notify_on=frozenset(self.notify_on.split(",")) if self.notify_on else NOTIFY_DEFAULT,
            active=self.active,
        )


class AlertRow(Base):
    """鳴らした記録（履歴表示と、通知の速さの計測に使う）。"""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    subscription_id: Mapped[str] = mapped_column(String(32), index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    station_id: Mapped[str] = mapped_column(String(64))
    train_number: Mapped[str] = mapped_column(String(32))
    destination: Mapped[str] = mapped_column(String(64), default="")
    direction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="arrived")
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()


# ---- 読み書きの入口（アプリ側はこの関数だけを使う） ----


def create_user(db: Session) -> UserRow:
    user = UserRow()
    db.add(user)
    db.commit()
    return user


def load_active_subscriptions(db: Session) -> list[Subscription]:
    """索引を組み立てるための読み出し（起動時と、購読の変更時だけ呼ぶ）。"""

    rows = db.scalars(select(SubscriptionRow).where(SubscriptionRow.active)).all()
    return [row.to_domain() for row in rows]


def record_alert(db: Session, sub: Subscription, event, kind: str) -> AlertRow:
    row = AlertRow(
        user_id=sub.user_id,
        subscription_id=sub.id,
        line_id=event.line_id,
        station_id=getattr(event, "station_id", ""),
        train_number=event.train_number,
        destination=getattr(event, "destination", ""),
        direction=getattr(event, "direction", None),
        kind=kind,
        delay_minutes=getattr(event, "delay_minutes", 0),
    )
    db.add(row)
    db.commit()
    return row
