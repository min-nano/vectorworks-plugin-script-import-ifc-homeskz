"""シートレイヤ(伏図)の命令の組み立て。vs 非依存。

モデルデータ(ストーリ・通り芯・基礎など)を取り込んだ後に、特定のデザインレイヤ群を
表示するビューポートを配置したシートレイヤを作るための命令(sheet 命令)を
組み立てる。IFC そのものからシート構成を読み取るわけではなく、取り込んだ要素の
有無からどのシートを作るべきかを判断する。

作成するシート:

- **基礎伏図**(``build_foundation_sheet_commands``): 基礎要素(立上り・底盤・
  アンカーボルト)が取り込まれる場合にだけ作成する(基礎が無ければ表示すべき
  レイヤが生成されずビューポートが空になるため)。シートレイヤ番号 ``1``・タイトル
  ``基礎伏図``、表示レイヤは 底盤(``F-底盤``)・立上り(``F-立上り``)・
  アンカーボルト(``F-アンカーボルト``)・通り芯(``共通``)。
- **各階の柱梁伏図**(``build_floor_framing_sheet_commands``): ストーリごとに 1 枚。
  シートレイヤ番号は基礎伏図(``1``)に続けて ``2`` から順に振る。タイトルは
  最下階から ``1階床伏図``・``2階床伏図``・…、最上階は ``小屋伏図``。表示レイヤは
  各階の横架材(``n-横架材天端``、最上階は ``n-軒高``)・柱(``n-柱``)・通り芯(``共通``)。
  加えて一般階(最上階以外)は床(``n-FL``)も表示し、最下階には基礎がある場合に
  アンカーボルト(``F-アンカーボルト``)も表示する。
- **母屋伏図**(``build_moya_sheet_commands``): 最上階(屋根)の母屋・棟木(と将来の
  垂木)を梁と分けて表示する 1 枚。シートレイヤ番号は柱梁伏図の最後(小屋伏図)に
  続けて振る。表示レイヤは母屋(``R-母屋``)・小屋束記号(``R-小屋束``)・通り芯
  (``共通``)。母屋を支える小屋束の位置を小屋束記号(柱束伏図記号 PIO)で示す。
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
    LEVEL_BEAM_TOP,
    LEVEL_COLUMN,
    LEVEL_EAVES,
    LEVEL_FL,
    LEVEL_KOYAZUKA_MARK,
    LEVEL_MOYA,
    LEVEL_UNDER_COLUMN,
    collect_stories,
    layer_prefix_for,
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

# 柱梁伏図(各階)シートの構成
# 最上階のタイトル(それ以外は "{階番号}階床伏図")
FLOOR_PLAN_ROOF_TITLE = '小屋伏図'
# 柱梁伏図のシートレイヤ番号の開始値。基礎伏図(番号 1)に続けて 2 から振る。
FLOOR_PLAN_START_NUMBER = 2

# 母屋伏図シートの構成。母屋・棟木(と将来の垂木)を梁と分けて表示する 1 枚。
# 柱梁伏図の最後(小屋伏図)に続けてシートレイヤ番号を振る。
MOYA_PLAN_TITLE = '母屋伏図'


def build_foundation_sheet_commands(
    ifc_file: ifcopenshell.file,
) -> list[SheetCommand]:
    """基礎伏図シートの sheet 命令を組み立てて返す。

    基礎要素が存在する場合に基礎伏図シートを 1 枚だけ返す。基礎が無ければ
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


def floor_plan_title(index: int, is_top: bool) -> str:
    """柱梁伏図シートのタイトルを返す(最上階は 小屋伏図、それ以外は n階床伏図)。"""
    return FLOOR_PLAN_ROOF_TITLE if is_top else f'{index + 1}階床伏図'


def build_floor_framing_sheet_commands(
    ifc_file: ifcopenshell.file,
) -> list[SheetCommand]:
    """各階の柱梁伏図シートの sheet 命令を組み立てて返す。

    ストーリ 1 つにつき伏図 1 枚。表示レイヤは横架材・柱・通り芯を基本とし、
    最上階以外は床(FL)を加える。最下階には基礎がある場合にアンカーボルトも加える。
    最下階以外は直下階の柱を記号化する下階柱記号レイヤ(``n-下階柱``)も加える。
    ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    foundation = has_foundation(ifc_file)
    commands: list[SheetCommand] = []
    n = len(stories)
    for i in range(n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        # 横架材レイヤは一般階=横架材天端、最上階=軒高。
        beam_level = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layers = [f'{prefix}-{beam_level}', f'{prefix}-{LEVEL_COLUMN}']
        # 最下階(i=0)以外は直下階の柱を記号化する下階柱記号レイヤを表示する。
        if i >= 1:
            layers.append(f'{prefix}-{LEVEL_UNDER_COLUMN}')
        if not is_top:
            # 最下階には基礎(アンカーボルト)がある場合に表示する。
            if i == 0 and foundation:
                layers.append(LAYER_FOUNDATION_ANCHOR)
            layers.append(f'{prefix}-{LEVEL_FL}')
        layers.append(TARGET_LAYER)
        title = floor_plan_title(i, is_top)
        number = str(FLOOR_PLAN_START_NUMBER + i)
        commands.append({
            'number': number,
            'title': title,
            'viewport': {
                'drawing_title': title,
                'drawing_number': number,
                'layers': layers,
            },
        })
    return commands


def build_moya_sheet_commands(
    ifc_file: ifcopenshell.file,
) -> list[SheetCommand]:
    """母屋伏図シートの sheet 命令を組み立てて返す。

    最上階(屋根)の母屋・棟木(と将来の垂木)を梁と分けて表示する伏図を 1 枚返す。
    シートレイヤ番号は柱梁伏図の最後(小屋伏図)に続けて振る。表示レイヤは
    母屋(``R-母屋``)・小屋束記号(``R-小屋束``)・通り芯(``共通``)。母屋を支える
    小屋束の位置を小屋束記号(柱束伏図記号 PIO)で示す。ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    if not stories:
        return []
    top_idx = len(stories) - 1
    prefix = layer_prefix_for(top_idx, True)
    # 番号: 基礎伏図(1)+各階柱梁伏図(ストーリ数)の次
    number = str(FLOOR_PLAN_START_NUMBER + len(stories))
    return [{
        'number': number,
        'title': MOYA_PLAN_TITLE,
        'viewport': {
            'drawing_title': MOYA_PLAN_TITLE,
            'drawing_number': number,
            'layers': [
                f'{prefix}-{LEVEL_MOYA}',
                f'{prefix}-{LEVEL_KOYAZUKA_MARK}',
                TARGET_LAYER,
            ],
        },
    }]


def build_sheet_commands(ifc_file: ifcopenshell.file) -> list[SheetCommand]:
    """sheet 命令のリストを組み立てて返す。

    基礎伏図(基礎がある場合のみ)に続けて、各階の柱梁伏図、最後に母屋伏図を
    組み立てる。
    """
    return [
        *build_foundation_sheet_commands(ifc_file),
        *build_floor_framing_sheet_commands(ifc_file),
        *build_moya_sheet_commands(ifc_file),
    ]
