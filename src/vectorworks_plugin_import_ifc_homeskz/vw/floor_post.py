"""floor_post 命令の描画。床束をハイブリッドシンボルとして配置する。

各床束を大引下の 2D 位置に ``vs.Symbol`` でハイブリッドシンボル(``床束``)として
配置する。高さの基準は基礎底盤上端(底盤天端)で、配置先レイヤ(F-床束)が
ストーリレベル(床束=底盤天端に揃える)にバインドされているため、シンボルは
そのレイヤ平面(=底盤上端)に配置される。命令自体は高さ情報を持たない。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が基礎ストーリの
床束レベルとして生成する。未生成 = 基礎ストーリが無い場合であり、勝手にレイヤを
作らない。アンカーボルトと同じ扱い)。
"""
from __future__ import annotations

import vs

from ..document import FloorPostCommand


def draw_floor_post(command: FloorPostCommand) -> None:
    """floor_post 命令 1 件をハイブリッドシンボルとして配置する。

    ``vs.Symbol`` にシンボル名・配置座標(POINT)・回転角(0)を渡して配置する。
    高さはアクティブレイヤ(F-床束=底盤上端)の平面で決まる。
    """
    x, y = command['position']
    vs.Symbol(command['symbol'], (x, y), 0)


def execute_floor_posts(commands: list[FloorPostCommand]) -> int:
    """floor_post 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_floor_post(command)
        count += 1

    return count
