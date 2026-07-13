"""column 命令の描画。VectorWorks 構造材ツールで柱を鉛直材として配置する。

柱は梁と同じ構造材ツール (StructuralMember) で描く。拡張パッケージの
柱・間柱ツールはスクリプト操作に対して不安定なため、安定して扱える標準の
構造材ツールに置き換えている。鉛直パス(下端→上端)に断面 width×depth の
プロファイルを与えて配置し、構造用途 (StructuralUse) を命令の structural_use
(管柱・通し柱="4"=柱、小屋束="5"=小屋束)で設定する。

**柱の高さはパスのジオメトリ(下端の絶対 Z + 柱高さ)で決まり、
SetObjectStoryBound は使わない。** 構造材ツールの高さバインドはバインドで指定した
高さをパス由来の部材長に**加算**するため、鉛直材の柱では両者が同一方向(Z)に
重なり部材長が二重になって上端が崩れる(例: 高さ 783.6 の小屋束にバインド
オフセット 783.6 を与えると部材長 1567.6 になり上端が 783.6 高く描かれる)。梁は
部材長が水平方向でバインドが Z 方向のため二重にならない。柱は Move3D で下端の
絶対位置へ配置したパスの高さでそのまま描く。
"""
from __future__ import annotations

import vs

from ..document import ColumnCommand

PLUGIN_NAME = 'StructuralMember'
STYLE_NAME = '木質構造材_柱・束'


def draw_column(command: ColumnCommand) -> None:
    """column 命令 1 件を構造材ツールで鉛直材として描画する。

    パスはローカル原点 (0,0,0) から鉛直方向(高さ分)に定義し、
    CreateCustomObjectPath 後に Move3D で下端の絶対位置 (XY + 下端 Z) へ移動する。
    続いて構造用途 (StructuralUse) を命令の structural_use (柱="4"/小屋束="5") で
    設定する。高さはパスのジオメトリで決まるため SetObjectStoryBound は使わない
    (鉛直材ではバインドの高さがパス由来の部材長に加算され上端が二重になるため。
    モジュール docstring 参照)。
    断面は width×depth の矩形プロファイル。member_id(柱頭・柱脚金物の仕様を
    含む構造材 ID)を MemberID フィールドに格納する。プラグインスタイル
    (STYLE_NAME)を SetPluginStyle で関連付ける。SetPluginStyle はパラメータの
    関連付けまでで、スタイルが決める描画属性(コンポーネントのクラス/マテリアル=
    テクスチャ等)はプッシュされない。描画属性は execute_columns が全配置後に
    UpdateStyledObjects でまとめて反映する(#56 の不具合)。個別フィールドはスタイル
    関連付けの後に設定するため、スタイルの既定値は本命令の実測値で上書きされる。
    プラグインが利用できない場合は断面の矩形にフォールバックする。
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
        vs.SetClass(obj, command['class'])
        vs.SetPluginStyle(obj, STYLE_NAME)
        vs.SetRField(obj, PLUGIN_NAME, 'MemberID', command['member_id'])
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileShape', 'Rectangle')
        vs.SetRField(obj, PLUGIN_NAME, 'MajorBreadth', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'MajorDepth', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'B', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'D', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'MemberType', '2')
        # 構造用途: 管柱・通し柱="4"(柱)、小屋束="5"(小屋束)。小屋束を柱用途に
        # すると VW の柱高さモデルで上端の高さオフセットと部材長が矛盾し上端高さが
        # 崩れるため、命令が持つ structural_use をそのまま設定する。
        vs.SetRField(obj, PLUGIN_NAME, 'StructuralUse', command['structural_use'])
        vs.SetRField(obj, PLUGIN_NAME, 'AxisAlign', '4')  # 4=中央(上部中央=1から3×3グリッド0始まり)
        vs.SetRField(obj, PLUGIN_NAME, 'EndCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'StartCondition', '3')
        vs.SetRField(obj, PLUGIN_NAME, 'ProfileSeries', 'AISC (Inch)')
        vs.ResetObject(obj)
    else:
        # フォールバック: 断面の矩形
        vs.Rect(x - w / 2, y + d / 2, x + w / 2, y - d / 2)
        fallback_rect = vs.LNewObj()
        vs.SetClass(fallback_rect, command['class'])


def execute_columns(commands: list[ColumnCommand]) -> int:
    """column 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない)。

    全配置後に UpdateStyledObjects(STYLE_NAME) を 1 回呼び、当該スタイルの全
    オブジェクトをスタイルから更新して描画属性(テクスチャ等)を反映する(梁と同じ
    規約。SetPluginStyle はパラメータの関連付けまでで描画属性をプッシュしないため。
    #56)。by-instance の個別フィールドは保持したまま by-style の描画属性のみ更新する。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_column(command)
        count += 1

    if count > 0:
        vs.UpdateStyledObjects(STYLE_NAME)

    return count
