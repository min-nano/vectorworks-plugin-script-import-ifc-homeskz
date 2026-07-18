"""section 命令の実行。断面ビューポート(セクションビューポート)を生成する。

伏図(``vw/sheet.py``)が平面のビューポートを作るのに対し、この断面はシートレイヤ上に
**建物を鉛直面で切断した断面ビューポート**を作る。切断は命令の切断線 2 点
(``line_start`` / ``line_end``)を結ぶ鉛直面で行い、``look``(視線方向の第 3 点)の
側から見る。

VectorWorks の断面ビューポートは、切断線 2 点 + 視線方向の第 3 点 + 見込み深さ +
鉛直クリップ範囲 + 配置先シートレイヤを受け取る SDK 関数
``CreateSectionViewport(pt1, pt2, pt3, depth, startHeight, endHeight, vpLayer)`` で
生成する(VW 2026 は多くの SDK 関数を Python の ``vs`` に公開している)。この関数が
``vs`` に無い環境では、切断はできないが**建物のエレベーション(側面)ビュー**を
`CreateVP` + `SetViewMatrix` で作るフォールバックに切り替える(実オブジェクトの
スクリプト書き出しに現れる表現。断面ビューポートはスクリプト書き出しでは真の切断が
保存されず側面ビューとして書き出されるため、フォールバックはこれに倣う)。

**断面関数の有無・引数(3 点の向き・深さ・高さの意味)・フォールバックのビュー行列・
配置は VectorWorks 上で最終確認する方針**(他要素と同じく、本モジュール冒頭の名前付き
定数に集約する)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SectionCommand

# レイヤ種別(vs.CreateLayer): 2=プレゼンテーション(シート)レイヤ
_SHEET_LAYER_TYPE = 2

# シートレイヤタイトルのオブジェクト変数 selector(vw/sheet.py と同じ)。
_OV_SHEET_TITLE = 159

# ビューポートのオブジェクト変数 selector(vw/sheet.py と同じ)。
_OV_VP_DRAWING_TITLE = 1032   # 図面タイトル
_OV_VP_DRAWING_NUMBER = 1033  # 図番
_OV_VP_SCALE = 1003           # 縮尺 1:N の N
_OV_VP_PROJECT_2D = 1005      # Project 2D(BOOLEAN): True=2D/平面, False=3D(断面/側面)

# ビューポートのレイヤ/クラス表示種別: 0=表示, 1=非表示
_VP_VISIBLE = 0

# 断面ビューポートを生成する SDK 由来の vs 関数名。VW 2026 で ``vs`` に公開されている
# ことを前提にするが、無い環境ではフォールバック(側面ビュー)に切り替える。
_SECTION_FUNC = 'CreateSectionViewport'

# フォールバック(側面ビュー)のビュー回転角 (度)。実オブジェクトのスクリプト書き出しの
# ``SetViewMatrix(vp, offX, 0, offZ, -90, -90, 0)`` に合わせる(切断線が Y 方向に走る
# 中央断面を -X 側から見る側面ビュー。VW 上で確認する)。
_FALLBACK_VIEW_ROTATION = (-90.0, -90.0, 0.0)


def _get_or_create_sheet_layer(number: str) -> Any:
    """シートレイヤ番号(=レイヤ名)でシートレイヤを取得または作成して返す。"""
    layer_h = vs.GetObject(number)
    if layer_h == vs.Handle(0):
        layer_h = vs.CreateLayer(number, _SHEET_LAYER_TYPE)
    return layer_h


def _show_all(viewport: Any, sheet_layer: Any) -> None:
    """断面ビューポートで全デザインレイヤ・全クラスを表示にする。

    断面は建物全体の切断面を見せるため、伏図のようにレイヤを絞らず全デザインレイヤを
    表示する(ビューポートの親であるシートレイヤ自身は除く)。クラスも全て表示する。
    """
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        if layer_h != sheet_layer:
            vs.SetVPLayerVisibility(viewport, layer_h, _VP_VISIBLE)
        layer_h = vs.NextLayer(layer_h)
    for i in range(1, vs.ClassNum() + 1):
        vs.SetVPClassVisibility(viewport, vs.ClassList(i), _VP_VISIBLE)


def _create_fallback_viewport(command: SectionCommand, sheet_layer: Any) -> Any:
    """断面関数が無い環境で、側面(エレベーション)ビューのビューポートを作って返す。

    切断はできないが、切断線の幾何から建物を真横から見た側面ビューを
    ``CreateVP`` + ``SetViewMatrix`` で作る(スクリプト書き出しに現れる表現)。
    ビュー行列は切断線が Y 方向に走る(X 一定)ことを前提に、実オブジェクトの
    書き出しの関係(offX = −(切断線の最大 Y)、offZ = −(切断線の X))で与える。
    ビューポートが作れなければ None。
    """
    obj = vs.CreateVP(sheet_layer)
    if obj == vs.Handle(0):
        return None
    cut_x = command['line_start'][0]
    y_far = max(command['line_start'][1], command['line_end'][1])
    rot_x, rot_y, rot_z = _FALLBACK_VIEW_ROTATION
    # 3D(側面)ビューにする(2D/平面ではない)。
    vs.SetObjectVariableBoolean(obj, _OV_VP_PROJECT_2D, False)
    vs.SetViewMatrix(obj, -y_far, 0.0, -cut_x, rot_x, rot_y, rot_z)
    vs.ResetObject(obj)
    return obj


def _create_section_viewport(command: SectionCommand, sheet_layer: Any) -> Any:
    """断面ビューポートを生成して返す。断面関数が無ければフォールバックする。

    ``vs.CreateSectionViewport(pt1, pt2, pt3, depth, startHeight, endHeight, vpLayer)``
    に切断線 2 点・視線方向の第 3 点・見込み深さ・鉛直クリップ範囲・シートレイヤを
    渡す。関数が ``vs`` に無い環境、または生成に失敗した(NIL を返した)場合は側面
    ビューのフォールバックに切り替える。
    """
    if not hasattr(vs, _SECTION_FUNC):
        return _create_fallback_viewport(command, sheet_layer)
    x1, y1 = command['line_start']
    x2, y2 = command['line_end']
    lx, ly = command['look']
    obj = vs.CreateSectionViewport(
        (x1, y1), (x2, y2), (lx, ly),
        command['depth'], command['start_height'], command['end_height'],
        sheet_layer,
    )
    if obj is None or obj == vs.Handle(0):
        return _create_fallback_viewport(command, sheet_layer)
    return obj


def draw_section(command: SectionCommand) -> bool:
    """section 命令 1 件を断面ビューポートとして描画する。

    シートレイヤ(番号=レイヤ名)を取得/作成しタイトルを設定してから、その上に
    断面ビューポートを生成し、全デザインレイヤ・全クラスを表示にして縮尺・図面
    タイトル・図番を設定し、指定位置へ移動して ``vs.UpdateVP`` で更新する。
    シートレイヤやビューポートが作れなければ False。
    """
    sheet_layer = _get_or_create_sheet_layer(command['number'])
    if sheet_layer == vs.Handle(0):
        return False
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_TITLE, command['title'])
    obj = _create_section_viewport(command, sheet_layer)
    if obj is None or obj == vs.Handle(0):
        return False
    vs.SetName(obj, command['drawing_title'])
    _show_all(obj, sheet_layer)
    vs.SetObjectVariableReal(obj, _OV_VP_SCALE, command['scale'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_TITLE, command['drawing_title'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_NUMBER, command['drawing_number'])
    # シートレイヤ上の指定位置(左上)へ移動する(スクリプト書き出しと同じ
    # GetBBox + HMove の方式)。
    x, y = command['position']
    p1, _p2 = vs.GetBBox(obj)
    left, top = p1
    vs.HMove(obj, x - left, y - top)
    vs.UpdateVP(obj)
    return True


def execute_sections(commands: list[SectionCommand]) -> int:
    """section 命令のリストを実行し、作成した断面ビューポート数を返す。"""
    count = 0
    for command in commands:
        if draw_section(command):
            count += 1
    return count
