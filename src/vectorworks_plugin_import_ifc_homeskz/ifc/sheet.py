"""シートレイヤ(伏図)の命令の組み立て。vs 非依存。

モデルデータ(ストーリ・通り芯・基礎など)を取り込んだ後に、特定のデザインレイヤ群を
表示するビューポートを配置した 1 枚のシートレイヤを作るための命令(sheet 命令)を
組み立てる。IFC そのものからシート構成を読み取るわけではなく、取り込んだ要素の
有無からどのシートを作るべきかを判断する。

現状は **基礎伏図** の 1 枚のみ:

- 基礎要素(立上り・底盤・アンカーボルト)が取り込まれる場合にだけ作成する
  (基礎が無ければ表示すべきレイヤが生成されずビューポートが空になるため)。
- シートレイヤ番号 ``1``・タイトル ``基礎伏図``、ビューポートの図面タイトルも
  ``基礎伏図``・図番 ``1``。
- ビューポートには 底盤(``F-底盤``)・立上り(``F-立上り``)・アンカーボルト
  (``F-アンカーボルト``)・通り芯(``共通``)のレイヤを表示する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import SheetCommand
from .footing import has_foundation
from .grid import TARGET_LAYER
from .story import (
    LAYER_FOUNDATION_ANCHOR,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
)

if TYPE_CHECKING:
    import ifcopenshell

# 基礎伏図シートの構成
FOUNDATION_PLAN_SHEET_NUMBER = '1'
FOUNDATION_PLAN_SHEET_TITLE = '基礎伏図'
# ビューポートに表示するレイヤ(底盤・立上り・アンカーボルト・通り芯)
FOUNDATION_PLAN_LAYERS = [
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LAYER_FOUNDATION_ANCHOR,
    TARGET_LAYER,
]


def build_sheet_commands(ifc_file: ifcopenshell.file) -> list[SheetCommand]:
    """sheet 命令のリストを組み立てて返す。

    現状は基礎要素が存在する場合に基礎伏図シートを 1 枚だけ返す。基礎が無ければ
    空リストを返す(表示すべき基礎レイヤが生成されないため)。
    """
    if not has_foundation(ifc_file):
        return []
    return [{
        'number': FOUNDATION_PLAN_SHEET_NUMBER,
        'title': FOUNDATION_PLAN_SHEET_TITLE,
        'viewport': {
            'drawing_title': FOUNDATION_PLAN_SHEET_TITLE,
            'drawing_number': FOUNDATION_PLAN_SHEET_NUMBER,
            'layers': list(FOUNDATION_PLAN_LAYERS),
        },
    }]
