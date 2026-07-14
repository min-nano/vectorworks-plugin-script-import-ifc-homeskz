"""fire_brace 命令の描画。火打をハイブリッドシンボルとして配置する。

各火打を横架材接合部の内側面交点(基準点)に ``vs.Symbol`` でハイブリッド
シンボル(``鋼製火打``)として配置する。回転角は命令の ``angle``(火打の向き)。
高さの基準は横架材天端(最上階は軒高)で、配置先レイヤがストーリレベルに
バインドされているため、シンボルはそのレイヤ平面に配置される。命令自体は
高さ情報を持たない。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
"""
from __future__ import annotations

import vs

from ..document import FireBraceCommand


def draw_fire_brace(command: FireBraceCommand) -> None:
    """fire_brace 命令 1 件をハイブリッドシンボルとして配置する。

    ``vs.Symbol`` にシンボル名・基準点座標(POINT)・回転角(度)を渡して配置する。
    高さはアクティブレイヤ(横架材天端 / 軒高)の平面で決まる。
    """
    x, y = command['position']
    vs.Symbol(command['symbol'], (x, y), command['angle'])


def execute_fire_braces(commands: list[FireBraceCommand]) -> int:
    """fire_brace 命令のリストを描画し、配置数を返す。

    配置先レイヤ(横架材天端 / 軒高)が存在しない命令はスキップする
    (レイヤは story 命令が生成する。未生成 = その階のストーリ設定がスキップ
    された場合であり、勝手にレイヤを作らない)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_fire_brace(command)
        count += 1

    return count
