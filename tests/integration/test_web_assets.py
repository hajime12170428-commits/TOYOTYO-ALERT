"""画面の部品の検査（Ver2）。

実際に起きた不具合の再発防止：
初回起動でアラーム画面が常に表示された。原因は、CSSの`display: flex`が
HTMLの`hidden`属性（ブラウザ標準の非表示）より強かったため。
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def test_hidden印を打ち消さないCSSになっている():
    """★再発防止：`[hidden]`を最優先で非表示にする行が必ずある。"""
    css = (WEB / "static" / "style.css").read_text(encoding="utf-8")

    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", css), (
        "style.cssに `[hidden] { display: none !important; }` がありません。"
        "これがないと、display指定を持つ部品（.alarm等）が常に表示されます。"
    )


def test_アラームと初回案内は最初から隠されている():
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert re.search(r'<div id="alarm"[^>]*\bhidden\b', html), "アラームにhidden印がない"
    assert re.search(r'<div id="setup"[^>]*\bhidden\b', html), "初回案内にhidden印がない"


def test_表示指定を持つ部品にはhidden印の検査が効く():
    """display指定つきの部品（.alarm / .setup）が増えたときの見張り。
    ここで数が増えたら、その部品もhidden運用か確認すること。"""
    css = (WEB / "static" / "style.css").read_text(encoding="utf-8")

    overlay_rules = re.findall(r"\.(alarm|setup)\s*\{[^}]*display:", css)
    assert sorted(set(overlay_rules)) == ["alarm", "setup"]


def test_画面更新のたびに保存番号を上げる運用が保たれている():
    """sw.jsのキャッシュ名に版番号があること（古い画面が配られ続けるのを防ぐ）。"""
    sw = (WEB / "sw.js").read_text(encoding="utf-8")

    m = re.search(r'const CACHE = "toyocho-v(\d+)"', sw)
    assert m, "sw.jsのCACHE名が `toyocho-v番号` 形式ではありません"
    assert int(m.group(1)) >= 3  # 不具合修正時にv3へ上げた


def test_ページ本体はサーバー優先で取りに行く():
    """画面を直しても古い画面が出続けないための方式（navigate＝ネット優先）。"""
    sw = (WEB / "sw.js").read_text(encoding="utf-8")

    assert 'mode === "navigate"' in sw
