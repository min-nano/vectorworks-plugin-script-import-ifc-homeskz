"""column 命令の描画。VectorWorks 木造BIM 柱・間柱ツールで柱を配置する。"""
from __future__ import annotations

import vs

from ..document import ColumnCommand

PLUGIN_NAME = '柱・間柱'


def draw_column(command: ColumnCommand) -> None:
    """column 命令 1 件を柱・間柱ツールで描画する。

    柱はローカル原点 (0, 0) に生成し、CreateCustomObject 後に Move3D で
    絶対位置（XY + 配置 Z 高さ）へ移動する。これは VW 柱・間柱ツールが
    期待する配置パターンと一致する。
    プラグインが利用できない場合は断面の矩形にフォールバックする。
    """
    x, y = command['position']
    w = int(round(command['width']))
    d = int(round(command['depth']))
    h = int(round(command['height']))

    obj = vs.CreateCustomObject(PLUGIN_NAME, 0, 0, 0)
    if obj != vs.Handle(0):
        # ローカル原点から実際の配置位置へ移動
        vs.ResetOrientation3D()
        vs.Move3D(x, y, command['elevation'])
        vs.SetRField(obj, PLUGIN_NAME, 'Type', command['column_type'])
        vs.SetRField(obj, PLUGIN_NAME, 'SecShape', '矩形')
        vs.SetRField(obj, PLUGIN_NAME, 'Width', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'Depth', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'Height', str(h))
        vs.SetRField(obj, PLUGIN_NAME, 'Rad', str(int(round(min(w, d) / 2))))
        vs.SetRField(obj, PLUGIN_NAME, 'Dia', str(w))
        vs.ResetObject(obj)
    else:
        # フォールバック: 断面の矩形
        vs.Rect(x - w / 2, y + d / 2, x + w / 2, y - d / 2)
        vs.LNewObj()


def execute_columns(commands: list[ColumnCommand]) -> int:
    """column 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする（レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない）。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_column(command)
        count += 1

    return count
