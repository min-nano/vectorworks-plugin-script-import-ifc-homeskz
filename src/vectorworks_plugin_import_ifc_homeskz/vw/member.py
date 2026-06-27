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
    始端と終端の天端 Z(elevation/end_elevation)が異なる傾斜梁
    (登り梁・隅木等)は Z 成分を持つ 3D パスとして描画する。
    配置後、始端/終端の高さ基準を SetObjectStoryBound でストーリレベル
    (横架材天端、最上階は軒高)にバインドする。これにより構造材ツールの
    高さ基準が "レイヤの高さ" のまま offset 0 で実ジオメトリと矛盾し、
    再描画/編集時に高さがリセットされる問題を防ぐ。
    プラグインが利用できない場合は通常の直線にフォールバックする。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']
    z1 = command['elevation']
    z2 = command['end_elevation']

    # パスをローカル座標で作成 (始点=原点、終点=方向×長さ)
    path_h = vs.CreateNurbsCurve(0, 0, 0, False, 1)
    vs.AddVertex3D(path_h, x2 - x1, y2 - y1, z2 - z1)

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
        vs.Move3D(x1, y1, z1)
        vs.SetClass(obj, command['class'])
        # 高さ基準をストーリレベルにバインドする(始端=0、終端=1。boundType=2=Story)。
        # これで構造材ツールの高さ基準が "レイヤの高さ"・offset 0 のまま実ジオメトリ
        # と矛盾せず、編集時に高さがリセットされない。
        start = command['start_bound']
        end = command['end_bound']
        vs.SetObjectStoryBound(
            obj, 0, 2, start['story_offset'], start['level'], start['offset'])
        vs.SetObjectStoryBound(
            obj, 1, 2, end['story_offset'], end['level'], end['offset'])
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
        fallback_line = vs.LNewObj()
        vs.SetClass(fallback_line, command['class'])


def execute_members(commands: list[MemberCommand]) -> int:
    """member 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない)。
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
