"""column 命令の描画。VectorWorks 木造BIM 柱・間柱ツールで柱を配置する。"""
from __future__ import annotations

import vs

from ..document import ColumnCommand, StoryBound

PLUGIN_NAME = '柱・間柱'

# SetObjectStoryBound の boundType: 0=LayerZ, 1=DefaultWallHeight, 2=Story
BOUND_TYPE_STORY = 2
# 上下端それぞれの story bound 識別子 (0=上端, 1=下端)
BOUND_ID_TOP = 0
BOUND_ID_BOTTOM = 1

# 柱・間柱ツールの伏図記号関連フィールド（ツールが日本語名のため内部名も日本語）
FIELD_SHOW_PLAN_SYMBOL = '伏図記号を表示'
FIELD_PLAN_LAYER = '伏図レイヤ'
# 伏図記号表示を有効にするブール値（VW のブールフィールドは 'True'/'False'）
PLAN_SYMBOL_ON = 'True'


def _set_story_bound(obj: object, bound_id: int, bound: StoryBound) -> None:
    """柱の上端/下端の高さ基準をストーリレベル基準で設定する。"""
    vs.SetObjectStoryBound(
        obj, bound_id, BOUND_TYPE_STORY,
        bound['story'], bound['level'], bound['offset'],
    )


def draw_column(command: ColumnCommand) -> None:
    """column 命令 1 件を柱・間柱ツールで描画する。

    柱はローカル原点 (0, 0) に生成し、CreateCustomObject 後に Move3D で
    XY 位置へ移動する。上下端の高さは固定値ではなく SetObjectStoryBound で
    ストーリレベル基準（下=横架材天端、上=上階の横架材天端 or 軒高）に
    バインドし、階高変更に追従させる（Z 方向の高さはこのバインドが決める）。
    伏図記号を表示し、伏図レイヤを当該階の柱(伏図)レイヤに設定する。
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
        # 上下端の高さ基準をストーリレベルにバインド（Z 高さを決定する）
        _set_story_bound(obj, BOUND_ID_TOP, command['top_bound'])
        _set_story_bound(obj, BOUND_ID_BOTTOM, command['bottom_bound'])
        vs.SetRField(obj, PLUGIN_NAME, 'Type', command['column_type'])
        vs.SetRField(obj, PLUGIN_NAME, 'SecShape', '矩形')
        # 伏図記号を表示し、伏図レイヤを当該階の柱(伏図)レイヤに設定する
        vs.SetRField(obj, PLUGIN_NAME, FIELD_SHOW_PLAN_SYMBOL, PLAN_SYMBOL_ON)
        vs.SetRField(obj, PLUGIN_NAME, FIELD_PLAN_LAYER, command['plan_layer'])
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
