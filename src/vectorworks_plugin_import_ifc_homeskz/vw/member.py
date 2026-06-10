"""member 命令の描画。VectorWorks 構造材ツールで部材を配置する。"""
from __future__ import annotations

import vs

from ..document import MemberCommand

PLUGIN_NAME = 'StructuralMember'


def draw_member(command: MemberCommand) -> None:
    """member 命令 1 件を構造材ツールで描画する。

    パスはローカル原点 (0,0,0) から方向ベクトルで定義し、
    CreateCustomObjectPath 後に Move3D で絶対位置へ移動する。
    これは VW 構造材ツールの期待する配置パターンと一致する。
    プラグインが利用できない場合は通常の直線にフォールバックする。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']

    # パスをローカル座標で作成 (始点=原点、終点=方向×長さ)
    path_h = vs.CreateNurbsCurve(0, 0, 0, False, 1)
    vs.AddVertex3D(path_h, x2 - x1, y2 - y1, 0)

    w = int(round(command['width']))
    h = int(round(command['height']))
    vs.BeginGroup()
    vs.ClosePoly()
    vs.Poly(0, 0, 0, h, w, h, w, 0)
    vs.EndGroup()
    profile_h = vs.LNewObj()

    obj = vs.CreateCustomObjectPath(PLUGIN_NAME, path_h, profile_h)
    if obj != vs.Handle(0):
        # ローカル原点から実際の配置位置へ移動
        vs.ResetOrientation3D()
        vs.Move3D(x1, y1, command['elevation'])
        vs.SetRField(obj, PLUGIN_NAME, 'MemberID', command['member_id'])
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileShape', 'Rectangle')
        vs.SetRField(obj, PLUGIN_NAME, 'MajorBreadth', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'MajorDepth', str(h))
        vs.SetRField(obj, PLUGIN_NAME, 'B', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'D', str(h))
        vs.SetRField(obj, PLUGIN_NAME, 'MemberType', '2')
        vs.SetRField(obj, PLUGIN_NAME, 'StructuralUse', '1')
        vs.SetRField(obj, PLUGIN_NAME, 'AxisAlign', '1')
        vs.SetRField(obj, PLUGIN_NAME, 'EndCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'StartCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileSeries', 'AISC (Inch)')
        vs.ResetObject(obj)
    else:
        # フォールバック: 通常の直線
        vs.MoveTo(x1, y1)
        vs.LineTo(x2, y2)
        vs.LNewObj()


def execute_members(commands: list[MemberCommand]) -> int:
    """member 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする（レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない）。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_member(command)
        count += 1

    return count
