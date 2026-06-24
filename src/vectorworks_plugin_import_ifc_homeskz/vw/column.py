"""column 命令の描画。VectorWorks 構造材ツールで柱を鉛直材として配置する。

柱は梁と同じ構造材ツール (StructuralMember) で描く。拡張パッケージの
柱・間柱ツールはスクリプト操作に対して不安定なため、安定して扱える標準の
構造材ツールに置き換えている。鉛直パス(下端→上端)に断面 width×depth の
プロファイルを与え、絶対 Z の固定パスとして描画する(ストーリレベルへの
高さバインドは使わない)。
"""
from __future__ import annotations

import vs

from ..document import ColumnCommand

PLUGIN_NAME = 'StructuralMember'


def draw_column(command: ColumnCommand) -> None:
    """column 命令 1 件を構造材ツールで鉛直材として描画する。

    パスはローカル原点 (0,0,0) から鉛直方向(高さ分)に定義し、
    CreateCustomObjectPath 後に Move3D で下端の絶対位置 (XY + 下端 Z) へ移動する。
    断面は width×depth の矩形プロファイル。member_id(柱頭・柱脚金物の仕様を
    含む構造材 ID)を MemberID フィールドに格納する。プラグインが利用できない
    場合は断面の矩形にフォールバックする。
    """
    x, y = command['position']
    z_bottom = command['elevation']
    w = int(round(command['width']))
    d = int(round(command['depth']))
    h = int(round(command['height']))

    # パスをローカル座標で作成 (始点=原点、終点=鉛直に高さ分)
    path_h = vs.CreateNurbsCurve(0, 0, 0, False, 1)
    vs.AddVertex3D(path_h, 0, 0, h)

    # 断面プロファイル(width×depth の矩形、パス軸が断面中心を通るよう原点中心で定義)
    vs.BeginGroup()
    vs.ClosePoly()
    vs.Poly(-w / 2, -d / 2, -w / 2, d / 2, w / 2, d / 2, w / 2, -d / 2)
    vs.EndGroup()
    profile_h = vs.LNewObj()

    obj = vs.CreateCustomObjectPath(PLUGIN_NAME, path_h, profile_h)
    if obj != vs.Handle(0):
        # ローカル原点から実際の配置位置(柱下端・断面中心の絶対位置)へ移動
        vs.ResetOrientation3D()
        vs.Move3D(x, y, z_bottom)
        vs.SetRField(obj, PLUGIN_NAME, 'MemberID', command['member_id'])
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileShape', 'Rectangle')
        vs.SetRField(obj, PLUGIN_NAME, 'MajorBreadth', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'MajorDepth', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'B', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'D', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'MemberType', '2')
        vs.SetRField(obj, PLUGIN_NAME, 'StructuralUse', '1')
        vs.SetRField(obj, PLUGIN_NAME, 'AxisAlign', '4')  # 4=中央(上部中央=1から3×3グリッド0始まり)
        vs.SetRField(obj, PLUGIN_NAME, 'EndCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'StartCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileSeries', 'AISC (Inch)')
        vs.ResetObject(obj)
    else:
        # フォールバック: 断面の矩形
        vs.Rect(x - w / 2, y + d / 2, x + w / 2, y - d / 2)
        vs.LNewObj()


def execute_columns(commands: list[ColumnCommand]) -> int:
    """column 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない)。
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
