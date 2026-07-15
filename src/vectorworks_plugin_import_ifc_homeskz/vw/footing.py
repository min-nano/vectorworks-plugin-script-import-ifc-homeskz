"""wall / slab 命令の描画。基礎の立上り(壁)・底盤/地中梁(スラブ)を配置する。

立上りは ``vs.Wall`` で壁オブジェクトを、底盤・地中梁は外形ポリゴンから
``vs.CreateSlab`` でスラブオブジェクトを生成する。いずれも高さ基準を
``SetObjectStoryBound`` でストーリレベルにバインドする(梁・柱と同じ規約)。
立上りには壁スタイル(``WALL_STYLE_NAME``)を ``SetWallStyle`` で適用する
(オフセットは 0/0 で壁芯に揃える)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SlabCommand, WallCommand, WallJoinCommand

WALL_STYLE_NAME = '基礎 - 木造ベタ基礎150mm'

# 壁結合(JoinWalls)の引数。capped(結合部を閉じるか)は命令ごとに指定する
# (天端高さの異なる立上りは低いほうを閉じて高いほうに結合する=capped=True、
# 同じ高さはコンクリート一体のため閉じない=capped=False)。showAlerts=False で
# 結合失敗時のダイアログを抑止する(インポート中に手動操作を求められないように)。
_JOIN_SHOW_ALERTS = False


def draw_wall(command: WallCommand) -> Any:
    """wall 命令 1 件を壁オブジェクトとして描画し、壁ハンドルを返す。

    壁厚を ``DoubLines`` で設定してから ``Wall`` で壁芯線から壁を生成し、
    下端・上端の高さ基準をストーリレベルにバインドする(boundType=2=Story)。
    壁が生成できない場合は壁芯の直線にフォールバックし、None を返す(壁結合の
    対象にならないため)。

    バインドには**壁専用の ``SetWallOverallHeights``** を使う。汎用の
    ``SetObjectStoryBound`` では壁の高さ基準が確定せず、壁がデザインレイヤの
    「壁の高さ(レイヤ設定)」(Default Wall Height)に従ってしまう(構造材・
    スラブでは ``SetObjectStoryBound`` が効くが、壁は専用関数が必要)。
    ``SetWallOverallHeights`` で下端/上端を直接ストーリレベルにバインドすることで
    レイヤの壁高さ設定に依存せず実形状どおりの高さになる。story 引数(0=自階・
    1=上階・2=下階)は ``story_offset`` の 0/1 とそのまま一致する。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']

    vs.DoubLines(command['thickness'])
    vs.Wall(x1, y1, x2, y2)
    obj = vs.LNewObj()
    if obj != vs.Handle(0):
        vs.SetClass(obj, command['class'])
        vs.SetWallStyle(obj, WALL_STYLE_NAME, 0.0, 0.0)
        bottom = command['bottom_bound']
        top = command['top_bound']
        vs.SetWallOverallHeights(
            obj,
            2, bottom['story_offset'], bottom['level'], bottom['offset'],
            2, top['story_offset'], top['level'], top['offset'])
        vs.ResetObject(obj)
        return obj
    # フォールバック: 壁芯の直線
    vs.MoveTo(x1, y1)
    vs.LineTo(x2, y2)
    fallback_line = vs.LNewObj()
    vs.SetClass(fallback_line, command['class'])
    return None


def draw_slab(command: SlabCommand) -> None:
    """slab 命令 1 件をスラブオブジェクトとして描画する。

    外形ポリゴンを閉じた多角形として作成し、``CreateSlab`` でスラブにする。
    スラブ天端の絶対 Z を ``SetSlabHeight`` で設定し、天端の高さ基準を底盤天端
    レベルにバインドする。スラブが生成できない場合は外形ポリゴンにフォールバック
    する。

    **``SetSlabHeight`` はスラブ厚ではなく天端高さ(Coordinate)を設定する**。
    以前はここに厚みを渡していたため天端が厚み分だけ高く描画されていた
    (柱・梁の高さ二重加算と同種の不具合)。スラブ厚はスラブスタイルのコンポーネント
    が決めるため、天端高さ(``elevation``、絶対 Z)を渡す。基礎ストーリは GL=0 の
    ため、この絶対 Z はストーリ基準高さと一致する。
    """
    boundary = command['boundary']

    vs.ClosePoly()
    vs.BeginPoly()
    vs.MoveTo(boundary[0][0], boundary[0][1])
    for point in boundary[1:]:
        vs.LineTo(point[0], point[1])
    vs.EndPoly()
    poly_h = vs.LNewObj()

    slab = vs.CreateSlab(poly_h)
    if slab != vs.Handle(0):
        vs.SetClass(slab, command['class'])
        vs.SetSlabHeight(slab, command['elevation'])
        bound = command['bound']
        vs.SetObjectStoryBound(
            slab, 0, 2, bound['story_offset'], bound['level'], bound['offset'])
        vs.ResetObject(slab)
    else:
        # フォールバック: 外形ポリゴン
        vs.SetClass(poly_h, command['class'])


def execute_walls(
    commands: list[WallCommand], handles: dict[int, Any] | None = None,
) -> int:
    """wall 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。

    ``handles`` に dict を渡すと、命令のインデックス(commands 内の位置)をキーに
    配置した壁ハンドルを記録する(壁結合 ``execute_wall_joins`` の関連付けに使う。
    横架材ハンドルと同じ受け渡し方式)。フォールバック描画(壁が作れない)や
    レイヤ未生成でスキップした命令は記録しない。
    """
    count = 0
    for index, command in enumerate(commands):
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        obj = draw_wall(command)
        if handles is not None and obj is not None:
            handles[index] = obj
        count += 1
    return count


def execute_wall_joins(
    commands: list[WallJoinCommand], handles: dict[int, Any],
) -> int:
    """wall_join 命令のリストを実行して交差する立上りを結合し、結合数を返す。

    ``handles`` は ``execute_walls`` が記録した壁インデックス→壁ハンドルの dict。
    各命令の ``a`` / ``b`` で 2 つの壁ハンドルを引き、``vs.JoinWalls`` で結合する。
    どちらかの壁が未配置(レイヤ未生成・フォールバック描画でハンドル未記録)の
    命令はスキップする。ピック点(どの端を結合するか)は両壁とも交点を渡し、
    結合種別は命令の ``join_type``(1=T・2=L・3=X)を joinModifier に、
    命令の ``capped``(天端高さの異なる立上りは結合部を閉じる)を capped に渡す。
    """
    count = 0
    for command in commands:
        first = handles.get(command['a'])
        second = handles.get(command['b'])
        if first is None or second is None:
            continue
        px, py = command['point']
        vs.JoinWalls(
            first, second, (px, py), (px, py),
            command['join_type'], command['capped'], _JOIN_SHOW_ALERTS)
        count += 1
    return count


def execute_slabs(commands: list[SlabCommand]) -> int:
    """slab 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        draw_slab(command)
        count += 1
    return count
