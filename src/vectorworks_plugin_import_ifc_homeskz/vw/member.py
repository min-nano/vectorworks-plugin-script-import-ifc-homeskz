"""member 命令の描画。VectorWorks 構造材ツールで部材を配置する。"""
from __future__ import annotations

import vs

from ..document import MemberCommand

PLUGIN_NAME = 'StructuralMember'
STYLE_NAME = '木質構造材_横架材'


def draw_member(command: MemberCommand) -> None:
    """member 命令 1 件を構造材ツールで描画する。

    パスは平面(プラン)投影でローカル原点 (0,0,0) から作成し、
    CreateCustomObjectPath 後に Move3D で絶対位置へ移動する。
    これは VW 構造材ツールの期待する配置パターンと一致する。
    始端/終端の高さ(傾斜梁=登り梁・隅木等の天端 Z の差を含む)は
    配置後の SetObjectStoryBound(start_bound/end_bound)で与える。
    **パスに Z 成分(傾斜)を持たせてはならない。** 構造材ツールの高さ
    バインドは指定した高さ差をパス由来の部材長に**加算**するため、
    パスにも傾斜を持たせると傾斜が二重に適用され終端が実際の 2 倍の高さに
    描画される(柱の二重加算(#54)と同種の問題。水平梁は差が 0 なので影響
    しなかった)。よってパスは水平にし、傾斜は始端/終端の高さバインドだけで
    表す。バインドは同時に、構造材ツールの高さ基準が "レイヤの高さ" のまま
    offset 0 で実ジオメトリと矛盾し再描画/編集時に高さがリセットされる問題も
    防ぐ(横架材天端、最上階は軒高)。
    配置後にプラグインスタイル(STYLE_NAME)を SetPluginStyle で関連付ける。
    SetPluginStyle はスタイルの関連付け(パラメータ)までで、スタイルが決める
    描画属性(コンポーネントのクラス/マテリアル=テクスチャ等)はオブジェクトへ
    プッシュされない。描画属性は execute_members が全配置後に UpdateStyledObjects
    でまとめて反映する(下記参照。#56 の不具合)。個別フィールドはスタイル関連付けの
    後に設定するため、スタイル既定のパラメータは本命令の実測値で上書きされる。
    プラグインが利用できない場合は通常の直線にフォールバックする。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']
    z1 = command['elevation']

    # パスをローカル座標の平面投影で作成 (始点=原点、終点=XY 方向ベクトル)。
    # Z(傾斜)はパスに持たせず start_bound/end_bound の高さバインドで与える
    # (パスにも持たせると傾斜が二重加算される。docstring 参照)。
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
        vs.Move3D(x1, y1, z1)
        vs.SetClass(obj, command['class'])
        vs.SetPluginStyle(obj, STYLE_NAME)
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

    全配置後に UpdateStyledObjects(STYLE_NAME) を 1 回呼び、当該スタイルの全
    オブジェクトをスタイルから更新して描画属性(テクスチャ等)を反映する。
    SetPluginStyle はスタイルの関連付け(パラメータ)までで描画属性をプッシュ
    しないため、これを呼ばないとテクスチャ等が反映されない(#56。OIP での手動適用は
    リンク+この更新の両方を行う)。UpdateStyledObjects は by-instance の個別
    フィールド(寸法・MemberID 等)は保持したまま by-style の描画属性のみ更新する。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_member(command)
        count += 1

    if count > 0:
        vs.UpdateStyledObjects(STYLE_NAME)

    return count
