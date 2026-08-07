# 日時ユーティリティ
#
# サーバーがどのタイムゾーンで動いていても(RenderはUTC)、
# 表示・集計は常に日本時間で行う。

from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst():
    return datetime.now(JST)


def now_str():
    """通知・履歴用のタイムスタンプ文字列(JST)"""
    return now_jst().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    """統計の「今日」判定用の日付文字列(JST)"""
    return now_jst().strftime("%Y-%m-%d")
