# 監視対象列車の位置表示(表示専用・監視ロジックとは独立)
#
# 在線位置APIの now(1駅=停車中/2駅=駅間走行)と路線の駅順データから、
# 現在位置・次の駅・監視駅までの残り駅数・到着目安を計算する。

# 到着目安の係数(駅間+停車でおよそ2分/駅)
AVG_MINUTES_PER_STATION = 2

# 列番未指定の監視で表示する接近列車の最大数
TRACK_LIMIT = 5


def _infer_direction(train, index, base):
    """停車中の列車の進行方向(+1/-1)を推定する。不明なら 0。

    行先駅が路線上にあればそれを優先し、なければ「○○方面」表記から推定する。
    """
    destination = train.get("destination", "")
    if destination in index and index[destination] != base:
        return 1 if index[destination] > base else -1

    direction_text = train.get("direction_text", "")
    if direction_text.endswith("方面"):
        head = direction_text[:-2]
        if head in index and index[head] != base:
            return 1 if index[head] > base else -1

    return 0


def build_train_status(line, target_station, train):
    """1本の列車について位置・次駅・監視駅までの残り駅数を計算する。"""
    stations = line["stations"]
    index = {s: i for i, s in enumerate(stations)}

    raw_now = train.get("now", []) or []
    known = [s for s in raw_now if s in index]

    status = {
        "number": train.get("number", ""),
        "type": train.get("type", ""),
        "destination": train.get("destination", ""),
        "delay": train.get("delay_text", ""),
        "position": "→".join(raw_now) if raw_now else "不明",
        "now_stations": known,  # 路線上の在線位置(路線図描画用)
        "direction": 0,         # +1=駅リスト末尾方向 / -1=先頭方向 / 0=不明
        "next_station": None,
        "remaining": None,      # 監視駅まで残り駅数(0=到着)
        "eta_minutes": None,    # 到着目安(分)
        "approaching": None,    # True=監視駅へ接近中 / False=逆方向 / None=不明
        "end_station": None,    # 進行方向の終点(行先が路線上ならその駅)
        "end_remaining": None,  # 終点までの残り駅数
    }

    if not known:
        # 直通先など路線外を走行中
        return status

    moving = len(known) == 2

    if moving:
        a, b = index[known[0]], index[known[1]]
        direction = 1 if b > a else -1
        base = b  # 次に到着する駅を基準にする
        status["next_station"] = known[1]
    else:
        base = index[known[0]]
        direction = _infer_direction(train, index, base)
        if direction:
            nxt = base + direction
            if 0 <= nxt < len(stations):
                status["next_station"] = stations[nxt]

    status["direction"] = direction

    if direction:
        destination = train.get("destination", "")
        if destination in index and (index[destination] - base) * direction >= 0:
            end_idx = index[destination]
        else:
            end_idx = len(stations) - 1 if direction == 1 else 0
        status["end_station"] = stations[end_idx]
        status["end_remaining"] = abs(end_idx - base) + (1 if moving else 0)
    elif not moving and train.get("destination", "") == known[0]:
        # 行先駅に停車中 = 終点到着済み(方向は定まらないが表示は出す)
        status["end_station"] = known[0]
        status["end_remaining"] = 0

    target = index.get(target_station)
    if target is None:
        return status

    if moving:
        status["remaining"] = abs(target - base) + 1
        status["approaching"] = (target - base) * direction >= 0
    else:
        status["remaining"] = abs(target - base)
        if status["remaining"] == 0:
            status["approaching"] = True  # 監視駅に到着
        elif direction:
            status["approaching"] = (target - base) * direction > 0
        # direction 不明のときは approaching = None のまま

    if status["approaching"]:
        status["eta_minutes"] = status["remaining"] * AVG_MINUTES_PER_STATION

    return status


def select_tracked(line, config, trains, limit=TRACK_LIMIT):
    """監視条件に合致する列車の位置情報リストを返す。

    - 列番指定あり: その列車を常に表示(逆方向でも表示する)
    - 列番指定なし: 行先で絞り込み、監視駅へ接近中の列車を近い順に最大 limit 件
    """
    if config["train"]:
        matched = [t for t in trains if t.get("number") == config["train"]]
    else:
        matched = trains
        if config["destination"]:
            matched = [
                t for t in matched
                if t.get("destination") == config["destination"]
            ]

    infos = [
        build_train_status(line, config["station"], t) for t in matched
    ]

    if not config["train"]:
        infos = [i for i in infos if i["approaching"]]
        infos.sort(key=lambda i: i["remaining"])
        infos = infos[:limit]

    return infos
