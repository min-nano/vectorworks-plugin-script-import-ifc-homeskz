"""sheet 命令の実行。シートレイヤとビューポートを生成する。

各 sheet 命令について、シートレイヤ(プレゼンテーションレイヤ)を作成し、その上に
指定したデザインレイヤ群を表示するビューポートを 1 つ配置する。ビューポートには
命令の ``layers`` に挙げたデザインレイヤだけを表示し、それ以外のデザインレイヤは
非表示にする。クラスは伏図に必要な要素が欠けないよう全クラスを表示にする。
ビューポートの縮尺は表示するデザインレイヤの縮尺に合わせる。

シートレイヤ番号は VectorWorks ではシートレイヤ(=レイヤ)の名前がそのまま担うため、
``vs.CreateLayer`` に番号を渡してレイヤ名=シートレイヤ番号にする。シートレイヤタイトル・
ビューポートの図面タイトル・図番は オブジェクト変数(``SetObjectVariableString`` の
selector)で設定する。selector 値は VectorWorks 公式のオブジェクト変数一覧に基づく
(``document.py`` のスキーマ参照)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SheetCommand, ViewportCommand

# レイヤ種別(vs.CreateLayer): 1=デザインレイヤ, 2=プレゼンテーション(シート)レイヤ
_SHEET_LAYER_TYPE = 2

# シートレイヤのオブジェクト変数 selector(SetObjectVariableString)。
# シートレイヤ番号はレイヤ名が担う(CreateLayer に番号を渡す)ため selector は無い。
_OV_SHEET_TITLE = 159   # シートレイヤタイトル

# ビューポートのオブジェクト変数 selector(SetObjectVariableString)
_OV_VP_DRAWING_TITLE = 1032   # 図面タイトル
_OV_VP_DRAWING_NUMBER = 1033  # 図番
# ビューポートの縮尺 selector(SetObjectVariableReal)。値はデザインレイヤと同じく
# 1:N の N(GetLScale が返す縮尺係数)。
_OV_VP_SCALE = 1003

# ビューポートのレイヤ表示種別(SetVPLayerVisibility): 0=表示, 1=グレー, 2=非表示
_VP_LAYER_VISIBLE = 0
_VP_LAYER_HIDDEN = 2

# ビューポートのクラス表示種別(SetVPClassVisibility): 0=表示, 1=グレー, 2=非表示
_VP_CLASS_VISIBLE = 0


def configure_viewport_layers(
    viewport: Any, target_layers: list[str], sheet_layer: Any,
) -> None:
    """ビューポートで target_layers だけを表示し、他のデザインレイヤを非表示にする。

    全デザインレイヤ(FLayer→NextLayer)を辿っていったん非表示にし(ビューポートの
    親であるシートレイヤ自身は除く)、そのあと target_layers を名前で引いて表示に
    戻す。これにより ``layers`` に挙げたレイヤだけが表示される。
    """
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        if layer_h != sheet_layer:
            vs.SetVPLayerVisibility(viewport, layer_h, _VP_LAYER_HIDDEN)
        layer_h = vs.NextLayer(layer_h)
    for name in target_layers:
        target_h = vs.GetLayerByName(name)
        if target_h != vs.Handle(0):
            vs.SetVPLayerVisibility(viewport, target_h, _VP_LAYER_VISIBLE)


def configure_viewport_classes(viewport: Any) -> None:
    """ビューポートで全クラスを表示にする。

    ビューポートは既定で一部クラスが非表示になることがあるため、ドキュメントの
    全クラス(``ClassNum``/``ClassList``)を辿って表示に設定する。表示レイヤは
    ``configure_viewport_layers`` で絞り込むが、クラスは伏図に必要な要素が欠けない
    よう全て表示する。
    """
    for i in range(1, vs.ClassNum() + 1):
        vs.SetVPClassVisibility(viewport, vs.ClassList(i), _VP_CLASS_VISIBLE)


def configure_viewport_scale(viewport: Any, target_layers: list[str]) -> None:
    """ビューポートの縮尺を表示するデザインレイヤの縮尺に合わせる。

    ``target_layers`` のうち最初に見つかったデザインレイヤの縮尺(``GetLScale``)を
    そのままビューポートの縮尺に設定する(伏図では表示レイヤの縮尺は揃っている)。
    レイヤが 1 つも見つからなければ何もしない(既定縮尺のまま)。
    """
    for name in target_layers:
        layer_h = vs.GetLayerByName(name)
        if layer_h != vs.Handle(0):
            vs.SetObjectVariableReal(viewport, _OV_VP_SCALE, vs.GetLScale(layer_h))
            return


def draw_viewport(
    viewport: ViewportCommand, sheet_layer: Any,
) -> None:
    """シートレイヤ上にビューポートを 1 つ生成し、表示レイヤ・図面タイトル・図番を設定する。

    ``vs.CreateVP`` でシートレイヤ上にビューポートを作り、表示レイヤを絞り込み、
    図面タイトル・図番を設定してから ``vs.UpdateVP`` で描画を更新する。
    ビューポートが生成できない場合は何もしない。
    """
    obj = vs.CreateVP(sheet_layer)
    if obj == vs.Handle(0):
        return
    vs.SetName(obj, viewport['drawing_title'])
    configure_viewport_layers(obj, viewport['layers'], sheet_layer)
    configure_viewport_classes(obj)
    configure_viewport_scale(obj, viewport['layers'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_TITLE, viewport['drawing_title'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_NUMBER, viewport['drawing_number'])
    vs.UpdateVP(obj)


def draw_sheet(command: SheetCommand) -> None:
    """sheet 命令 1 件をシートレイヤ + ビューポートとして描画する。

    シートレイヤ(プレゼンテーションレイヤ)を **シートレイヤ番号を名前として**
    作成し(VW ではシートレイヤ番号はレイヤ名が担う)、シートレイヤタイトルを
    設定してから、その上にビューポートを配置する。同じ番号のシートレイヤが既にある
    場合は再利用する。
    """
    number = command['number']
    sheet_layer = vs.GetObject(number)
    if sheet_layer == vs.Handle(0):
        sheet_layer = vs.CreateLayer(number, _SHEET_LAYER_TYPE)
    if sheet_layer == vs.Handle(0):
        return
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_TITLE, command['title'])
    draw_viewport(command['viewport'], sheet_layer)


def execute_sheets(commands: list[SheetCommand]) -> int:
    """sheet 命令のリストを実行し、作成シート数を返す。"""
    count = 0
    for command in commands:
        draw_sheet(command)
        count += 1
    return count
