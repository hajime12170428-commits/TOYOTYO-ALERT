# 路線マスタデータ(data/lines.json)の読み込み
#
# 路線を追加する場合はコードを変更せず data/lines.json に追記するだけでよい。

import json
import os

DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "lines.json",
)

REQUIRED_KEYS = ("id", "api_id", "name", "color", "stations", "destinations")


def _load():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    lines = data["lines"]

    # データ不備は起動時に検出して落とす(黙って壊れた状態で動かさない)
    seen_ids = set()
    for line in lines:
        for key in REQUIRED_KEYS:
            if not line.get(key):
                raise ValueError(
                    f"lines.json: {line.get('id', '?')} の {key} が未設定です"
                )
        if line["id"] in seen_ids:
            raise ValueError(f"lines.json: id '{line['id']}' が重複しています")
        seen_ids.add(line["id"])

        if len(set(line["stations"])) != len(line["stations"]):
            raise ValueError(f"lines.json: {line['id']} の駅名が重複しています")

    return lines


LINES = _load()
LINE_MAP = {line["id"]: line for line in LINES}


def get_line(line_id):
    """路線IDから路線定義を返す。未知のIDは None。"""
    return LINE_MAP.get(line_id)
