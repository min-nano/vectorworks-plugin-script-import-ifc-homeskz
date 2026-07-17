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
  床束(``F-床束``)・アンカーボルト(``F-アンカーボルト``)・通り芯(``共通``)。
  配筋(鉄筋 PIO)は立上り・底盤と同じレイヤに重ねて配置されるためレイヤでは絞れず、
  基礎伏図では配筋クラス(``04構造-01基礎-09鉄筋``)をビューポート単位で非表示に
  する(断面でのみ表示する要件)。
- **各階の柱梁伏図**(``build_floor_framing_sheet_commands``): ストーリごとに 1 枚。
  シートレイヤ番号は基礎伏図(``1``)に続けて ``2`` から順に振る。タイトルは
  最下階から ``1階床伏図``・``2階床伏図``・…、最上階は主屋根が架かる階番号を付けた
  ``{階数}階小屋伏図``(例 2 階建てなら ``2階小屋伏図``)。表示レイヤは
  各階の横架材(``n-横架材天端``、最上階は ``n-軒高``)・柱(``n-柱``)・通り芯(``共通``)。
  加えて**それより下の全階の柱レイヤ**(3階床伏図なら ``1-柱``・``2-柱``)も表示する
  (通し柱は起点となる下階の柱レイヤに描かれ当階の柱レイヤには現れないため、下階の
  柱を重ねないと通し柱が当階に無いように映る)。一般階(最上階以外)は床(``n-FL``)も
  表示し、最下階には基礎がある場合に
  アンカーボルト(``F-アンカーボルト``)も表示する。**直下階が下屋根の小屋組(母屋・
  棟木)を含む**場合、その母屋レイヤ(直下階の ``n-母屋``)を重ねて表示し、母屋が
  直下階の屋根に当たるためタイトルを ``{n}階床・{n-2}階母屋伏図``(最上階は
  ``{階数}階小屋・{n-2}階母屋伏図``)にする。下屋根の母屋は直下階の伏図では梁と
  重なるため、1 つ上の階の伏図に載せる(表示する伏図を 1 階分上げる)。
- **母屋伏図**(``build_moya_sheet_commands``): 最上階(屋根)の母屋・棟木・垂木を
  梁と分けて表示する 1 枚。シートレイヤ番号は柱梁伏図の最後(小屋伏図)に
  続けて振る。タイトルは主屋根が架かる階番号を付けた ``{階数}階母屋伏図``。表示
  レイヤは母屋(``R-母屋``)・垂木(``R-垂木``)・小屋束記号(``R-小屋束``)・通り芯
  (``共通``)。母屋を支える小屋束の位置を小屋束記号(柱束伏図記号 PIO)で示す。
  中間階の下屋根の母屋・垂木は専用シートにせず、1 つ上の階の柱梁伏図に重ねて表示する
  (上記)。

さらに ``build_legend_commands`` は基礎伏図に **グラフィック凡例**(VW 標準の
「グラフィック凡例」PIO)を配置する legend 命令を組み立てる。基礎伏図ビューポートに
表示されるシンボル(既定ではアンカーボルト)を対象にし、実際に配置された
アンカーボルトのシンボル(M12/M16)を ``土台用アンカーボルトM12`` /
``ホールダウン用アンカーボルトM16`` のラベル(コード内の固定マッピング)で並べる。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import (
    AnchorBoltCommand,
    LegendCommand,
    LegendItemCommand,
    SheetCommand,
)
from .anchor_bolt import SYMBOL_M12, SYMBOL_M16
from .footing import has_foundation
from .grid import TARGET_LAYER
from .rebar import CLASS_REBAR
from .story import (
    LAYER_FOUNDATION_ANCHOR,
    LAYER_FOUNDATION_FLOOR_POST,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LEVEL_BEAM_TOP,
    LEVEL_COLUMN,
    LEVEL_EAVES,
    LEVEL_FL,
    LEVEL_KOYAZUKA_MARK,
    LEVEL_MOYA,
    LEVEL_TARUKI,
    LEVEL_UNDER_COLUMN,
    collect_stories,
    collect_story_moya_flags,
    collect_story_roof_flags,
    layer_prefix_for,
)

if TYPE_CHECKING:
    import ifcopenshell

# 基礎伏図シートの構成
FOUNDATION_PLAN_SHEET_NUMBER = '1'
FOUNDATION_PLAN_SHEET_TITLE = '基礎伏図'
# ビューポートに表示するレイヤ(底盤・立上り・床束・アンカーボルト・通り芯)
FOUNDATION_PLAN_LAYERS = [
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LAYER_FOUNDATION_FLOOR_POST,
    LAYER_FOUNDATION_ANCHOR,
    TARGET_LAYER,
]
# 基礎伏図で非表示にするクラス。配筋(鉄筋 PIO)は立上り・底盤と同じレイヤに重ねて
# 配置されるためレイヤでは絞れない。基礎伏図では配筋を隠し、断面でのみ表示する
# (要件)ため配筋クラスをビューポート単位で非表示にする。
FOUNDATION_PLAN_HIDDEN_CLASSES = [CLASS_REBAR]

# 基礎伏図のグラフィック凡例の構成。基礎伏図ビューポートに表示されるシンボル
# (既定ではアンカーボルト)の凡例を配置する。
# シンボル名 → 表示ラベルのコード内固定マッピング(要件どおり)。
ANCHOR_BOLT_LEGEND_LABELS = {
    SYMBOL_M12: '土台用アンカーボルトM12',
    SYMBOL_M16: 'ホールダウン用アンカーボルトM16',
}
# 凡例に並べるシンボルの順序(M12 → M16)。実際に配置されたシンボルのうち
# この順で載せる。
ANCHOR_BOLT_LEGEND_ORDER = [SYMBOL_M12, SYMBOL_M16]
# 凡例のシートレイヤ上の配置点 (mm)。VW 上で最終調整する。
FOUNDATION_LEGEND_POSITION = [0.0, 0.0]

# 柱梁伏図(各階)シートの構成
# タイトルの種別ラベル。一般階は "床"、最上階は主屋根の "小屋"。いずれも階番号と
# 組み合わせて "{階番号}階床" / "{階数}階小屋" のように使う。
FLOOR_PLAN_FLOOR_LABEL = '床'
FLOOR_PLAN_ROOF_LABEL = '小屋'
# 柱梁伏図のシートレイヤ番号の開始値。基礎伏図(番号 1)に続けて 2 から振る。
FLOOR_PLAN_START_NUMBER = 2

# 母屋伏図シートの構成。母屋・棟木(と将来の垂木)を梁と分けて表示する 1 枚。
# 柱梁伏図の最後(小屋伏図)に続けてシートレイヤ番号を振る。タイトルは主屋根が
# 架かる階番号を付けた "{階数}階母屋伏図"。床伏図に重ねる下屋根の母屋ラベルにも使う。
MOYA_PLAN_LABEL = '母屋'


def build_foundation_sheet_commands(
    ifc_file: ifcopenshell.file,
) -> list[SheetCommand]:
    """基礎伏図シートの sheet 命令を組み立てて返す。

    基礎要素が存在する場合に基礎伏図シートを 1 枚だけ返す。基礎が無ければ
    空リストを返す(表示すべき基礎レイヤが生成されないため)。ビューポートは
    配筋クラス(``FOUNDATION_PLAN_HIDDEN_CLASSES``)を非表示にする(配筋は
    立上り・底盤と同じレイヤに重なるためレイヤでは絞れず、断面でのみ表示する要件)。
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
            'hidden_classes': list(FOUNDATION_PLAN_HIDDEN_CLASSES),
        },
    }]


def floor_plan_title(
    index: int, is_top: bool, count: int, has_moya_below: bool = False,
) -> str:
    """柱梁伏図シートのタイトルを返す。

    最上階は主屋根が架かる階番号を付けた ``{count-1}階小屋伏図``、それ以外は
    ``{index+1}階床伏図`` を基本とする。**直下階(``index-1`` 階)が下屋根の小屋組
    (母屋・棟木)を含む**場合(``has_moya_below``)、その母屋を 1 つ上のこの階の
    伏図に重ねて表示するためタイトルを ``…・{index-1}階母屋伏図`` とする(下屋根の
    母屋は直下階の屋根に当たり、直下階の伏図では梁と重なるため 1 階分上げる)。
    """
    if is_top:
        base = f'{count - 1}階{FLOOR_PLAN_ROOF_LABEL}'
    else:
        base = f'{index + 1}階{FLOOR_PLAN_FLOOR_LABEL}'
    if has_moya_below:
        return f'{base}・{index - 1}階{MOYA_PLAN_LABEL}伏図'
    return f'{base}伏図'


def build_floor_framing_sheet_commands(
    ifc_file: ifcopenshell.file,
) -> list[SheetCommand]:
    """各階の柱梁伏図シートの sheet 命令を組み立てて返す。

    ストーリ 1 つにつき伏図 1 枚。表示レイヤは横架材・柱・通り芯を基本とし、
    **それより下の全階の柱レイヤ**(3階床伏図なら ``1-柱``・``2-柱``)も加える(通し柱を
    表示するため)。最上階以外は床(FL)を加える。最下階には基礎がある場合に
    アンカーボルトも加える。最下階以外は直下階の柱を記号化する下階柱記号レイヤ
    (``n-下階柱``)も加える。
    **直下階が下屋根の小屋組(母屋・棟木)を含む**場合、その母屋レイヤ(直下階の
    ``n-母屋``)を重ねて表示する(下屋根の母屋は直下階の伏図では梁と重なるため
    1 つ上のこの階の伏図に載せる)。ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    foundation = has_foundation(ifc_file)
    moya_flags = collect_story_moya_flags(ifc_file)
    roof_flags = collect_story_roof_flags(ifc_file)
    commands: list[SheetCommand] = []
    n = len(stories)
    for i in range(n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        # 直下階(i-1)が下屋根(下屋)を持つ場合、その小屋組(母屋・棟木)・垂木は
        # 専用レイヤ((i-1)-母屋 / (i-1)-垂木)に分離され、直下階の屋根に当たる。直下階の
        # 伏図では梁と重なるため、1 つ上のこの階の伏図に重ねて表示する(表示する伏図を
        # 1 階分上げる)。下屋根は母屋を持たなくても屋根版=垂木があるため、垂木の重ね
        # 表示は屋根版の有無(roof_flags)で、母屋の重ね表示は母屋の有無(moya_flags)で
        # それぞれ判定する。
        has_moya_below = i >= 1 and moya_flags[i - 1]
        has_roof_below = i >= 1 and roof_flags[i - 1]
        # 横架材レイヤは一般階=横架材天端、最上階=軒高。
        beam_level = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layers = [f'{prefix}-{beam_level}', f'{prefix}-{LEVEL_COLUMN}']
        # 最下階(i=0)以外は直下階の柱を記号化する下階柱記号レイヤを表示する。
        if i >= 1:
            layers.append(f'{prefix}-{LEVEL_UNDER_COLUMN}')
        # それより下の全階の柱レイヤ(3階床伏図なら 1-柱・2-柱)も表示する。通し柱は
        # 起点となる下階の柱レイヤに立ち上がって描かれる(当階の柱レイヤには現れない)
        # ため、下階の柱レイヤを重ねないと通し柱が「当階に柱が無い」ように映ってしまう。
        # j<i の階はいずれも最上階ではないため layer_prefix_for(j, False)。
        for j in range(i):
            layers.append(f'{layer_prefix_for(j, False)}-{LEVEL_COLUMN}')
        # 直下階の下屋根の母屋((i-1)-母屋)・垂木((i-1)-垂木)をこの階の伏図に
        # 重ねて表示する(下屋根の小屋組は直下階の伏図では梁と重なるため 1 階分上げる)。
        # 母屋は母屋がある場合のみ、垂木は屋根版がある場合に表示する。
        if has_roof_below:
            below_prefix = layer_prefix_for(i - 1, False)
            if has_moya_below:
                layers.append(f'{below_prefix}-{LEVEL_MOYA}')
            layers.append(f'{below_prefix}-{LEVEL_TARUKI}')
        if not is_top:
            # 最下階には基礎(アンカーボルト)がある場合に表示する。
            if i == 0 and foundation:
                layers.append(LAYER_FOUNDATION_ANCHOR)
            layers.append(f'{prefix}-{LEVEL_FL}')
        layers.append(TARGET_LAYER)
        # タイトルの「…母屋伏図」表記は母屋がある場合のみ付ける(垂木だけの下屋根は
        # 既存のタイトルのまま垂木レイヤを重ねて表示する)。
        title = floor_plan_title(i, is_top, n, has_moya_below)
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

    最上階(屋根)の母屋・棟木・垂木を梁と分けて表示する伏図を 1 枚返す。
    シートレイヤ番号は柱梁伏図の最後(小屋伏図)に続けて振る。タイトルは主屋根が
    架かる階番号を付けた ``{階数}階母屋伏図``。表示レイヤは母屋(``R-母屋``)・
    垂木(``R-垂木``)・小屋束記号(``R-小屋束``)・通り芯(``共通``)。母屋を支える
    小屋束の位置を小屋束記号(柱束伏図記号 PIO)で示す。ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    if not stories:
        return []
    top_idx = len(stories) - 1
    prefix = layer_prefix_for(top_idx, True)
    # 番号: 基礎伏図(1)+各階柱梁伏図(ストーリ数)の次
    number = str(FLOOR_PLAN_START_NUMBER + len(stories))
    # タイトル: 主屋根が架かる最上階の階番号(=ストーリ数 - 1)を付ける
    title = f'{len(stories) - 1}階{MOYA_PLAN_LABEL}伏図'
    return [{
        'number': number,
        'title': title,
        'viewport': {
            'drawing_title': title,
            'drawing_number': number,
            'layers': [
                f'{prefix}-{LEVEL_MOYA}',
                f'{prefix}-{LEVEL_TARUKI}',
                f'{prefix}-{LEVEL_KOYAZUKA_MARK}',
                TARGET_LAYER,
            ],
        },
    }]


def build_legend_commands(
    ifc_file: ifcopenshell.file,
    anchor_bolts: list[AnchorBoltCommand],
) -> list[LegendCommand]:
    """基礎伏図のグラフィック凡例の legend 命令を組み立てて返す。

    基礎伏図ビューポートに表示されるシンボル(既定ではアンカーボルト)の凡例を
    1 つ返す。凡例に載せるシンボルは **実際に配置されたアンカーボルト**
    (``anchor_bolts`` に現れるシンボル)のうち ``ANCHOR_BOLT_LEGEND_LABELS`` に
    対応があるものだけを ``ANCHOR_BOLT_LEGEND_ORDER`` の順で採り、表示ラベルは
    コード内の固定マッピングで決める。基礎が無い(基礎伏図が作られない)場合や
    載せるシンボルが 1 つも無い場合は空リストを返す。
    """
    if not has_foundation(ifc_file):
        return []
    present = {command['symbol'] for command in anchor_bolts}
    items: list[LegendItemCommand] = [
        {'symbol': symbol, 'label': ANCHOR_BOLT_LEGEND_LABELS[symbol]}
        for symbol in ANCHOR_BOLT_LEGEND_ORDER
        if symbol in present and symbol in ANCHOR_BOLT_LEGEND_LABELS
    ]
    if not items:
        return []
    return [{
        'number': FOUNDATION_PLAN_SHEET_NUMBER,
        'position': list(FOUNDATION_LEGEND_POSITION),
        'items': items,
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
