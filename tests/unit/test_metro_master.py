"""東京メトロの路線・駅データの検証（Ver2）。

駅名の表記が上流データとずれると一致しなくなるため、ここで守る。
`-m live`を付けたときだけ、本物の上流と突き合わせる。
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from toyocho import metro

EXPECTED_STATION_COUNT = {
    "TokyoMetro_Ginza": 19,
    "TokyoMetro_Marunouchi": 25,
    "TokyoMetro_MarunouchiBranch": 4,
    "TokyoMetro_Hibiya": 22,
    "TokyoMetro_Tozai": 23,
    "TokyoMetro_Chiyoda": 20,
    "TokyoMetro_Yurakucho": 24,
    "TokyoMetro_Hanzomon": 14,
    "TokyoMetro_Namboku": 19,
    "TokyoMetro_Fukutoshin": 16,
}


def test_東京メトロの全路線がそろっている():
    assert len(metro.LINES) == 10  # 9路線＋丸ノ内線支線
    assert set(metro.line_ids()) == set(EXPECTED_STATION_COUNT)


@pytest.mark.parametrize("line_id,count", EXPECTED_STATION_COUNT.items())
def test_駅数が正しい(line_id, count):
    line = metro.get_line(line_id)
    assert line is not None
    assert len(line.stations) == count


def test_路線内に駅の重複がない():
    for line in metro.LINES:
        assert len(set(line.stations)) == len(line.stations), line.name


def test_方面は両端の駅に対応している():
    """方面名（例：中野方面）は、路線の端の駅名を含むこと。"""
    for line in metro.LINES:
        first, last = line.stations[0], line.stations[-1]
        assert any(first in d for d in line.directions), line.name
        assert any(last in d for d in line.directions), line.name


def test_路線を取り出せる():
    tozai = metro.get_line("TokyoMetro_Tozai")

    assert tozai is not None
    assert "東陽町" in tozai.stations
    assert "渋谷" not in tozai.stations  # 東西線に渋谷はない
    assert metro.get_line("存在しない路線") is None


@pytest.mark.live
@pytest.mark.parametrize("line_id", sorted(EXPECTED_STATION_COUNT))
def test_上流データの駅名がすべてマスタに含まれる(line_id):
    """本物の上流と突き合わせる（`pytest -m live`のときだけ実行）。"""
    url = f"https://nkth.info/traffic_info/ODPT/now?line={line_id.replace('TokyoMetro_', 'TokyoMetro_')}"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode())

    trains = list(payload.get("noRunning") or []) + list(payload.get("running") or [])
    seen = {s for t in trains for s in (t.get("now") or [])}
    known = set(metro.get_line(line_id).stations)

    未登録 = seen - known
    assert not 未登録, f"{line_id} にマスタ未登録の駅名: {sorted(未登録)}"
