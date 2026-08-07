# SQLite データ層
#
# 利用者(users)・通知履歴(history)・監視状態(monitors)を保存する。
# 履歴と統計は利用者IDで完全に分離される。
# 将来ログイン機能を追加する場合は users テーブルにアカウント情報を
# 紐付ければよい(利用者IDはそのまま使える)。

import os
import sqlite3
import threading

from timeutil import now_str, today_str

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 保存先は DATA_DIR で変更できる(Renderの永続ディスク /data など)。
# ファイル名は旧サービス名(TOYOCHO ALERT)由来だが、変更すると既存データが
# 読めなくなるため互換性のために維持している
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "toyotyo.db")

HISTORY_PAGE_LIMIT = 100  # 画面に返す履歴の最大件数

# init_db の多重実行を防ぐ
_init_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _init_lock:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = _connect()
        try:
            with conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id         TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     TEXT NOT NULL,
                        time        TEXT NOT NULL,
                        line        TEXT NOT NULL,
                        station     TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        train       TEXT NOT NULL,
                        is_test     INTEGER NOT NULL DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_history_user
                    ON history(user_id, id)
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS monitors (
                        user_id     TEXT PRIMARY KEY,
                        line_id     TEXT NOT NULL,
                        station     TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        train       TEXT NOT NULL,
                        active      INTEGER NOT NULL DEFAULT 0,
                        started_at  TEXT NOT NULL
                    )
                """)
        finally:
            conn.close()


def ensure_user(user_id):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)",
                (user_id, now_str()),
            )
    finally:
        conn.close()


def add_history(user_id, entry, is_test=False):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO history
                    (user_id, time, line, station, destination, train, is_test)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    entry["time"],
                    entry["line"],
                    entry["station"],
                    entry["destination"],
                    entry["train"],
                    1 if is_test else 0,
                ),
            )
    finally:
        conn.close()


def get_history(user_id, limit=HISTORY_PAGE_LIMIT):
    """利用者の通知履歴を新しい順に返す。"""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT time, line, station, destination, train
            FROM history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def get_stats(user_id):
    """利用者の累計・今日の通知数(テスト通知は除く)。"""
    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM history WHERE user_id = ? AND is_test = 0",
            (user_id,),
        ).fetchone()[0]

        today = conn.execute(
            """
            SELECT COUNT(*) FROM history
            WHERE user_id = ? AND is_test = 0 AND time LIKE ?
            """,
            (user_id, today_str() + "%"),
        ).fetchone()[0]
    finally:
        conn.close()

    return {"today": today, "total": total}


def save_monitor(user_id, line_id, station, destination, train):
    """監視開始を記録する(再起動時の復元に使う)。"""
    conn = _connect()
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitors
                    (user_id, line_id, station, destination, train,
                     active, started_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (user_id, line_id, station, destination, train, now_str()),
            )
    finally:
        conn.close()


def deactivate_monitor(user_id):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "UPDATE monitors SET active = 0 WHERE user_id = ?",
                (user_id,),
            )
    finally:
        conn.close()


def get_active_monitors():
    """再起動時に復元すべき監視の一覧。"""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT user_id, line_id, station, destination, train
            FROM monitors
            WHERE active = 1
            """
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]
