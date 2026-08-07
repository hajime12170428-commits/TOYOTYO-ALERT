# 路線マスタデータ(data/lines.json)の整合性テスト
import re

import pytest

from lines import LINES, get_line

EXPECTED_STATION_COUNTS = {
    "Ginza": 19,
    "Marunouchi": 25,
    "MarunouchiBranch": 4,
    "Hibiya": 22,
    "Tozai": 23,
    "Chiyoda": 20,
    "Yurakucho": 24,
    "Hanzomon": 14,
    "Namboku": 19,
    "Fukutoshin": 16,
}


def test_all_10_lines_defined():
    assert len(LINES) == 10
    assert {line["id"] for line in LINES} == set(EXPECTED_STATION_COUNTS)


def test_line_ids_unique():
    ids = [line["id"] for line in LINES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("line", LINES, ids=lambda l: l["id"])
def test_line_structure(line):
    assert line["api_id"] == f"TokyoMetro_{line['id']}"
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", line["color"])
    assert line["name"]
    assert len(line["stations"]) == EXPECTED_STATION_COUNTS[line["id"]]
    assert len(line["destinations"]) > 0
    # 駅名重複なし
    assert len(set(line["stations"])) == len(line["stations"])


def test_tozai_stations_preserved():
    """既存機能(東西線)の駅リストが壊れていないこと"""
    tozai = get_line("Tozai")
    assert tozai["stations"][0] == "中野"
    assert tozai["stations"][-1] == "西船橋"
    for station in ["木場", "東陽町", "門前仲町", "九段下", "高田馬場"]:
        assert station in tozai["stations"]


def test_tozai_destinations_preserved():
    """既存UIにあった行先が引き続き選択できること"""
    tozai = get_line("Tozai")
    for dest in ["中野", "三鷹", "東陽町", "西船橋", "東葉勝田台"]:
        assert dest in tozai["destinations"]


def test_get_line_unknown():
    assert get_line("Yamanote") is None
    assert get_line("") is None
