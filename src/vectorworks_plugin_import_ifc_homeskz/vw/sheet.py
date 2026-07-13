"""sheet 命令の実行。シートレイヤとビューポートを生成する。

各 sheet 命令について、シートレイヤ(プレゼンテーションレイヤ)を作成し、その上に
指定したデザインレイヤ群を表示するビューポートを 1 つ配置する。ビューポートには
命令の ``layers`` に挙げたデザインレイヤだけを表示し、それ以外のデザインレイヤは
非表示にする。

シートレイヤ番号・タイトル、ビューポートの図面タイトル・図番は VectorWorks の
オブジェクト変数(``SetObjectVariableString`` の selector)で設定する。selector 値は
VectorWorks 公式のオブジェクト変数一覧に基づく(``document.py`` のスキーマ参照)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SheetCommand, ViewportCommand

# レイヤ種別(vs.CreateLayer): 1=デザインレイヤ, 2=プレゼンテーション(シート)レイヤ
_SHEET_LAYER_TYPE = 2

# シートレイヤのオブジェクト変数 selector(SetObjectVariableString)
_OV_SHEET_NUMBER = 158  # シートレイヤ番号
_OV_SHEET_TITLE = 159   # シートレイヤタイトル

# ビューポートのオブジェクト変数 selector(SetObjectVariableString)
_OV_VP_DRAWING_TITLE = 1032   # 図面タイトル
_OV_VP_DRAWING_NUMBER = 1034  # 図番

# ビューポートのレイヤ表示種別(SetVPLayerVisibility): 0=表示, 1=グレー, 2=非表示
_VP_LAYER_VISIBLE = 0
_VP_LAYER_HIDDEN = 2


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
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_TITLE, viewport['drawing_title'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_NUMBER, viewport['drawing_number'])
    vs.UpdateVP(obj)


def draw_sheet(command: SheetCommand) -> None:
    """sheet 命令 1 件をシートレイヤ + ビューポートとして描画する。

    シートレイヤ(プレゼンテーションレイヤ)を作成し、シートレイヤ番号・タイトルを
    設定してから、その上にビューポートを配置する。同名のシートレイヤが既にある場合は
    再利用する。
    """
    title = command['title']
    sheet_layer = vs.GetObject(title)
    if sheet_layer == vs.Handle(0):
        sheet_layer = vs.CreateLayer(title, _SHEET_LAYER_TYPE)
    if sheet_layer == vs.Handle(0):
        return
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_NUMBER, command['number'])
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_TITLE, title)
    draw_viewport(command['viewport'], sheet_layer)


def execute_sheets(commands: list[SheetCommand]) -> int:
    """sheet 命令のリストを実行し、作成シート数を返す。"""
    count = 0
    for command in commands:
        draw_sheet(command)
        count += 1
    return count
