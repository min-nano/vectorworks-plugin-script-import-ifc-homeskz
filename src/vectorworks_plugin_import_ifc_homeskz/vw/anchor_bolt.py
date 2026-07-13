"""anchor_bolt 命令の描画。アンカーボルトをハイブリッドシンボルとして配置する。

各アンカーボルトを軸芯位置に ``vs.Symbol`` でハイブリッドシンボル
(``アンカーボルト_M12`` / ``アンカーボルト_M16``)として配置する。高さの基準は
基礎天端で、配置先レイヤ(F-アンカーボルト)がストーリレベル(基礎天端)に
バインドされているため、シンボルはそのレイヤ平面(=基礎天端)に配置される。
命令自体は高さ情報を持たない。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が基礎ストーリの
基礎天端レベルとして生成する)。
"""
from __future__ import annotations

import vs

from ..document import AnchorBoltCommand


def draw_anchor_bolt(command: AnchorBoltCommand) -> None:
    """anchor_bolt 命令 1 件をハイブリッドシンボルとして配置する。

    ``vs.Symbol`` にシンボル名・軸芯座標(POINT)・回転角(0)を渡して配置する。
    高さはアクティブレイヤ(F-アンカーボルト=基礎天端)の平面で決まる。
    """
    x, y = command['position']
    vs.Symbol(command['symbol'], (x, y), 0)


def execute_anchor_bolts(commands: list[AnchorBoltCommand]) -> int:
    """anchor_bolt 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する。
    未生成 = 基礎ストーリが無い場合であり、勝手にレイヤを作らない)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_anchor_bolt(command)
        count += 1

    return count
