"""東京メトロの路線・駅データ（Ver2）。

対象は**東京メトロのみ**（社長指示、2026-08-07）。他社への拡張は考えない。

路線と駅はめったに変わらないため、データベースには置かずここに持つ。
表を2つ減らせるうえ、初期データ投入の手順も要らなくなる。
駅名・方面名は**上流データの表記に合わせてある**（「霞ケ関」「市ケ谷」「雑司が谷」など）。
表記がずれると一致しなくなるため、`tests/test_metro_master.py`で
実データと突き合わせて検証している。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    id: str  # 上流データのかぎ（例：TokyoMetro_Tozai）
    name: str  # 表示名（例：東西線）
    color: str  # 路線カラー（画面で使う）
    directions: tuple[str, str]  # 方面（上流のdirection_textと同じ表記）
    stations: tuple[str, ...]  # 起点から終点までの順


LINES: tuple[Line, ...] = (
    Line(
        id="TokyoMetro_Ginza",
        name="銀座線",
        color="#FF9500",
        directions=("渋谷方面", "浅草方面"),
        stations=(
            "渋谷", "表参道", "外苑前", "青山一丁目", "赤坂見附", "溜池山王",
            "虎ノ門", "新橋", "銀座", "京橋", "日本橋", "三越前", "神田",
            "末広町", "上野広小路", "上野", "稲荷町", "田原町", "浅草",
        ),
    ),
    Line(
        id="TokyoMetro_Marunouchi",
        name="丸ノ内線",
        color="#F62E36",
        directions=("荻窪方面", "池袋方面"),
        stations=(
            "荻窪", "南阿佐ケ谷", "新高円寺", "東高円寺", "新中野", "中野坂上",
            "西新宿", "新宿", "新宿三丁目", "新宿御苑前", "四谷三丁目", "四ツ谷",
            "赤坂見附", "国会議事堂前", "霞ケ関", "銀座", "東京", "大手町",
            "淡路町", "御茶ノ水", "本郷三丁目", "後楽園", "茗荷谷", "新大塚", "池袋",
        ),
    ),
    Line(
        id="TokyoMetro_MarunouchiBranch",
        name="丸ノ内線（方南町支線）",
        color="#F62E36",
        directions=("中野坂上方面", "方南町方面"),
        stations=("中野坂上", "中野新橋", "中野富士見町", "方南町"),
    ),
    Line(
        id="TokyoMetro_Hibiya",
        name="日比谷線",
        color="#B5B5AC",
        directions=("中目黒方面", "北千住方面"),
        stations=(
            "中目黒", "恵比寿", "広尾", "六本木", "神谷町", "虎ノ門ヒルズ",
            "霞ケ関", "日比谷", "銀座", "東銀座", "築地", "八丁堀", "茅場町",
            "人形町", "小伝馬町", "秋葉原", "仲御徒町", "上野", "入谷",
            "三ノ輪", "南千住", "北千住",
        ),
    ),
    Line(
        id="TokyoMetro_Tozai",
        name="東西線",
        color="#009BBF",
        directions=("中野方面", "西船橋方面"),
        stations=(
            "中野", "落合", "高田馬場", "早稲田", "神楽坂", "飯田橋", "九段下",
            "竹橋", "大手町", "日本橋", "茅場町", "門前仲町", "木場", "東陽町",
            "南砂町", "西葛西", "葛西", "浦安", "南行徳", "行徳", "妙典",
            "原木中山", "西船橋",
        ),
    ),
    Line(
        id="TokyoMetro_Chiyoda",
        name="千代田線",
        color="#00BB85",
        directions=("代々木上原方面", "北綾瀬方面"),
        stations=(
            "代々木上原", "代々木公園", "明治神宮前", "表参道", "乃木坂", "赤坂",
            "国会議事堂前", "霞ケ関", "日比谷", "二重橋前", "大手町", "新御茶ノ水",
            "湯島", "根津", "千駄木", "西日暮里", "町屋", "北千住", "綾瀬", "北綾瀬",
        ),
    ),
    Line(
        id="TokyoMetro_Yurakucho",
        name="有楽町線",
        color="#C1A470",
        directions=("和光市方面", "新木場方面"),
        stations=(
            "和光市", "地下鉄成増", "地下鉄赤塚", "平和台", "氷川台", "小竹向原",
            "千川", "要町", "池袋", "東池袋", "護国寺", "江戸川橋", "飯田橋",
            "市ケ谷", "麴町", "永田町", "桜田門", "有楽町", "銀座一丁目",
            "新富町", "月島", "豊洲", "辰巳", "新木場",
        ),
    ),
    Line(
        id="TokyoMetro_Hanzomon",
        name="半蔵門線",
        color="#8F76D6",
        directions=("渋谷方面", "押上方面"),
        stations=(
            "渋谷", "表参道", "青山一丁目", "永田町", "半蔵門", "九段下", "神保町",
            "大手町", "三越前", "水天宮前", "清澄白河", "住吉", "錦糸町", "押上",
        ),
    ),
    Line(
        id="TokyoMetro_Namboku",
        name="南北線",
        color="#00AC9B",
        directions=("目黒方面", "赤羽岩淵方面"),
        stations=(
            "目黒", "白金台", "白金高輪", "麻布十番", "六本木一丁目", "溜池山王",
            "永田町", "四ツ谷", "市ケ谷", "飯田橋", "後楽園", "東大前", "本駒込",
            "駒込", "西ケ原", "王子", "王子神谷", "志茂", "赤羽岩淵",
        ),
    ),
    Line(
        id="TokyoMetro_Fukutoshin",
        name="副都心線",
        color="#9C5E31",
        directions=("和光市方面", "渋谷方面"),
        stations=(
            "和光市", "地下鉄成増", "地下鉄赤塚", "平和台", "氷川台", "小竹向原",
            "千川", "要町", "池袋", "雑司が谷", "西早稲田", "東新宿",
            "新宿三丁目", "北参道", "明治神宮前", "渋谷",
        ),
    ),
)

_BY_ID = {line.id: line for line in LINES}


def get_line(line_id: str) -> Line | None:
    return _BY_ID.get(line_id)


def line_ids() -> tuple[str, ...]:
    return tuple(_BY_ID)
