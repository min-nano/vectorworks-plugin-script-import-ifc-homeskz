"""joint 命令の描画。仕口をハイブリッドシンボルとして配置する。

受ける材のある横架材端部(梁端の中央上端)に ``vs.Symbol`` でハイブリッド
シンボル(``仕口``)を配置する。回転角は命令の ``angle``(梁端の向き=梁軸に沿って
端部から部材内側へ向かう方向)。高さの基準は横架材天端(最上階は軒高、母屋は
母屋)で、配置先レイヤがストーリレベルにバインドされているため、シンボルは
そのレイヤ平面に配置される。命令自体は高さ情報を持たない(火打と同じ扱い)。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
"""
from __future__ import annotations

import vs

from ..document import JointCommand


def draw_joint(command: JointCommand) -> None:
    """joint 命令 1 件をハイブリッドシンボルとして配置する。

    ``vs.Symbol`` にシンボル名・基準点座標(POINT)・回転角(度)を渡して配置する。
    高さはアクティブレイヤ(横架材天端 / 軒高 / 母屋)の平面で決まる。
    """
    x, y = command['position']
    vs.Symbol(command['symbol'], (x, y), command['angle'])


def execute_joints(commands: list[JointCommand]) -> int:
    """joint 命令のリストを描画し、配置数を返す。

    配置先レイヤ(横架材天端 / 軒高 / 母屋)が存在しない命令はスキップする
    (レイヤは story 命令が生成する。未生成 = その階のストーリ設定がスキップ
    された場合であり、勝手にレイヤを作らない。火打と同じ扱い)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_joint(command)
        count += 1

    return count
