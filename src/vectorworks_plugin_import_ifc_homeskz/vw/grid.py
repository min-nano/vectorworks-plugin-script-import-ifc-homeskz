"""grid 命令の描画。GridAxis プラグインオブジェクトを配置する。"""
from __future__ import annotations

import vs

from ..document import GridCommand

PLUGIN_NAME = 'GridAxis'


def draw_grid(command: GridCommand) -> None:
    """grid 命令 1 件を GridAxis オブジェクトとして描画する。

    プラグインが利用できない場合は通常の直線にフォールバックする。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']

    vs.BeginPoly()
    vs.MoveTo(x1, y1)
    vs.LineTo(x2, y2)
    vs.EndPoly()
    path_handle = vs.LNewObj()

    vs.BeginGroup()
    vs.EndGroup()
    profile_handle = vs.LNewObj()

    grid_obj = vs.CreateCustomObjectPath(PLUGIN_NAME, path_handle, profile_handle)

    if grid_obj != vs.Handle(0):
        vs.SetClass(grid_obj, command['class'])
        vs.SetRField(grid_obj, PLUGIN_NAME, 'Label', command['label'])
        vs.SetRField(grid_obj, PLUGIN_NAME, 'ShowBubbleAt', 'Start Point')
        vs.ResetObject(grid_obj)
    else:
        vs.MoveTo(x1, y1)
        vs.LineTo(x2, y2)
        fallback_line = vs.LNewObj()
        vs.SetClass(fallback_line, command['class'])


def execute_grids(commands: list[GridCommand]) -> int:
    """grid 命令のリストを描画し、描画本数を返す。

    配置先レイヤが存在しない場合は作成してアクティブにする。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            vs.CreateLayer(layer, 1)
        vs.Layer(layer)

        draw_grid(command)
        count += 1

    return count
