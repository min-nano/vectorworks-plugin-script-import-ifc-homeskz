"""floor 命令の描画。床板を床ツール(Floor オブジェクト)で配置する。

床ツールの Floor オブジェクトは ``vs.BeginFloor(thickness)`` で開始し、
2D 図形(平面外形の閉じたポリゴン)を描いてから ``vs.EndGroup()`` で確定する
(``BeginFloor`` の VW 公式ドキュメント: 「2D オブジェクト作成手続きでテンプレート
を定義し、EndGroup で完了する」)。作成後、床下端が横架材天端になるよう
``vs.Move3D`` で絶対 Z へ移動し、``vs.SetObjectStoryBound`` で高さ基準を
横架材天端レベルにバインドする(構造材・スラブと同じ規約。編集時に高さがずれない
ようにする)。床が作れない場合は外形ポリゴンにフォールバックする。

高さの与え方(Move3D の絶対 Z・厚みの伸びる向き・SetObjectStoryBound の
アンカー)は他の要素と同じく VectorWorks 上で最終確認する方針
(床下端 = 横架材天端 になることを確認する)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import FloorCommand


def _set_all_attributes_by_class(obj: Any) -> None:
    """オブジェクトの描画属性(太さ・色・パターン・透明度等)をすべてクラス属性に従わせる。

    ``SetClass`` はクラスを割り当てるだけで各描画属性は by-instance の既定値のまま残る
    ため、属性ごとの by-class 設定関数を個別に呼ぶ(``vw/column_mark.py``・
    ``vw/rebar.py`` と同じ規約)。
    """
    vs.SetPenColorByClass(obj)
    vs.SetFillColorByClass(obj)
    vs.SetLWByClass(obj)
    vs.SetLSByClass(obj)
    vs.SetFPatByClass(obj)
    vs.SetMarkerByClass(obj)
    vs.SetOpacityByClass(obj)


def draw_floor(command: FloorCommand) -> None:
    """floor 命令 1 件を床ツール(Floor オブジェクト)として描画する。

    ``vs.BeginFloor(thickness)`` で床を開始し、平面外形を閉じたポリゴンとして描いて
    ``vs.EndGroup()`` で床オブジェクトを確定する。作成後、床下端が横架材天端(命令の
    ``elevation``、絶対 Z)になるよう ``vs.Move3D`` で Z 方向に移動し、高さ基準を
    横架材天端レベルに ``vs.SetObjectStoryBound`` でバインドする(offset は床下端が
    横架材天端ちょうどのため 0)。床が生成できない場合は外形ポリゴンにフォールバックする。
    """
    boundary = command['boundary']

    vs.BeginFloor(command['thickness'])
    vs.ClosePoly()
    vs.BeginPoly()
    vs.MoveTo(boundary[0][0], boundary[0][1])
    for point in boundary[1:]:
        vs.LineTo(point[0], point[1])
    vs.EndPoly()
    vs.EndGroup()
    floor = vs.LNewObj()

    if floor != vs.Handle(0):
        # 床下端を横架材天端(絶対 Z)へ。床ツールは床を作成した層平面(Z=0)に
        # 置くため、Move3D で実際の高さへ移動する(構造材の Move3D と同じ規約)。
        vs.Move3D(0.0, 0.0, command['elevation'])
        vs.SetClass(floor, command['class'])
        # 描画属性(カラー・透明度等)をすべてクラス属性に従わせる。
        _set_all_attributes_by_class(floor)
        bound = command['bound']
        vs.SetObjectStoryBound(
            floor, 0, 2, bound['story_offset'], bound['level'], bound['offset'])
        vs.ResetObject(floor)
    else:
        # フォールバック: 外形ポリゴン
        vs.ClosePoly()
        vs.BeginPoly()
        vs.MoveTo(boundary[0][0], boundary[0][1])
        for point in boundary[1:]:
            vs.LineTo(point[0], point[1])
        vs.EndPoly()
        poly_h = vs.LNewObj()
        vs.SetClass(poly_h, command['class'])
        _set_all_attributes_by_class(poly_h)


def execute_floors(commands: list[FloorCommand]) -> int:
    """floor 命令のリストを描画し、配置数を返す。

    配置先レイヤ(``n-FL``)が存在しない命令はスキップする(レイヤは story 命令が
    生成する。未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        draw_floor(command)
        count += 1
    return count
