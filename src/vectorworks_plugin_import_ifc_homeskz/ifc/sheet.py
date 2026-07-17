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
  各階の横架材(``n-横架材天端``、最上階は ``n-軒高``)・通り芯(``共通``)に加え、
  **その伏図の切断レベルを span が含む柱レイヤ**(``{from}to{to}-柱``)を表示する。
  切断レベルはその階の床レベル(1 始まり=index+1)+0.25(``FLOOR_PLAN_CUT_OFFSET``)。
  これにより、その階を base とする柱の断面と、下から貫いてこの高さに達する通し柱が
  表示され、下屋の小屋束(to が半整数でその階の床に届かない)は上階の小屋伏図に写り
  込まない。一般階(最上階以外)は床(``n-FL``)も表示し、最下階には基礎がある場合に
  アンカーボルト(``F-アンカーボルト``)も表示する。下屋根(下屋)の小屋組
  (母屋・垂木・野地板)はこの柱梁伏図には重ねず、専用の母屋伏図に分けて表示する(下記)。
- **母屋伏図**(``build_moya_sheet_commands``): **屋根版(屋根面)を持つ階ごとに 1 枚**、
  その階の小屋組(母屋・垂木・野地板)を梁組と分けて表示する。最上階(屋根)の主屋根
  だけでなく、中間階に架かる下屋根(下屋)にも 1 枚ずつ作る(複雑な下屋根で母屋等の
  小屋組と梁組が重なって見にくくなるのを防ぐ)。シートレイヤ番号は各階の柱梁伏図の
  最後に続けて Elevation 昇順に振る。タイトルは屋根が架かる階番号を付けた
  ``{index}階母屋伏図``(例 2 階建てなら主屋根=``2階母屋伏図``、下屋根=``1階母屋伏図``)。
  表示レイヤは母屋(``n-母屋``、母屋がある階のみ)・垂木(``n-垂木``)・野地板
  (``n-野地板``)・通り芯(``共通``)に加え、**その伏図の切断レベル(その階の床レベル
  +0.75=``MOYA_PLAN_CUT_OFFSET``)を span が含む柱レイヤ**(``{from}to{to}-柱``)。
  これにより屋根を貫いて立ち上がる主屋の柱(管柱・通し柱、例 ``2to3``)が表示される。
  母屋伏図は母屋の上からの見下げ図なので小屋束の断面は出ず(切断が小屋束 span の
  to=半整数より高いため小屋束レイヤは含まれない)、母屋を支える小屋束の位置は平面の
  伏図記号で示す(小屋束伏図記号は span 方式への移行後に別途対応する)。

さらに legend 命令(VW 標準の「グラフィック凡例」PIO の配置)を組み立てる。

- ``build_legend_commands`` は **基礎伏図**にグラフィック凡例を配置する。基礎伏図
  ビューポートに表示されるシンボル(既定ではアンカーボルト)を対象にし、実際に
  配置されたアンカーボルトのシンボル(M12/M16)を ``土台用アンカーボルトM12`` /
  ``ホールダウン用アンカーボルトM16`` のラベル(コード内の固定マッピング)で並べる。
  関連付けるグラフィック凡例スタイルは ``基礎伏図凡例``。
- ``build_floor_legend_commands`` は **各柱梁伏図(床伏図・小屋伏図)と各母屋伏図**に
  グラフィック凡例を 1 つずつ配置する(基礎伏図と同様)。凡例に載せるシンボル・ラベルは
  グラフィック凡例スタイル ``床伏図凡例`` に焼き込むため命令は items を持たない。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import (
    AnchorBoltCommand,
    ColumnCommand,
    LegendCommand,
    LegendItemCommand,
    SheetCommand,
)
from .anchor_bolt import SYMBOL_M12, SYMBOL_M16
from .column import collect_column_spans
from .footing import has_foundation
from .grid import TARGET_LAYER
from .rebar import CLASS_REBAR
from .story import (
    LAYER_FOUNDATION_ANCHOR,
    LAYER_FOUNDATION_FLOOR_POST,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    LEVEL_FL,
    LEVEL_MOYA,
    LEVEL_NOJIITA,
    LEVEL_TARUKI,
    collect_stories,
    collect_story_moya_flags,
    collect_story_roof_flags,
    layer_prefix_for,
    plan_mark_layer_name,
)

# 柱梁伏図(床伏図・小屋伏図)の切断レベル。各階の床レベル(1 始まり=ストーリ index+1)
# より 0.25 だけ上をサンプルし、その階を base(from)とする柱の断面と、下から貫いて
# この高さに達する柱(通し柱)を表示する。span [from, to] がこの切断レベルを含む
# (from ≤ 切断 ≤ to)柱レイヤだけを載せることで、下屋の小屋束(例 ``2to2.5``、to=2.5)が
# 上階の小屋伏図(切断 3.25)に写り込まなくなる。
FLOOR_PLAN_CUT_OFFSET = 1.25

# 母屋伏図の柱の切断レベル。母屋伏図(story index ``i``、タイトル ``{i}階母屋伏図``)は
# 屋根(母屋)を見下げる図で、母屋を支える小屋束の断面は出さず、代わりに屋根を貫いて
# 立ち上がる主屋の柱(管柱・通し柱)を表示する。切断レベルは ``i + 1.75``=その階の
# 床レベル(``i + 1``)より 0.75 上=**その階の小屋束(span [i+1, i+1.5])を超え、
# 上階の床(``i + 2``)には届かない高さ**をサンプルする。これにより span [from, to] が
# この切断を含む(from ≤ 切断 ≤ to)柱レイヤ、すなわち下から貫いてこの高さに達する
# 主屋の柱(例 ``2to3``・``1to3``)だけが載り、母屋を支える下屋の小屋束
# (例 ``2to2.5``、to=2.5<2.75)は載らない(小屋束の断面は母屋伏図に出さない要件)。
# 例: 1階母屋伏図(i=1)=2.75、2階母屋伏図(i=2)=3.75。
MOYA_PLAN_CUT_OFFSET = 1.75

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
# 基礎伏図のグラフィック凡例に関連付けるプラグインスタイル名。ソース定義
# (シンボルをソースにし基礎伏図ビューポートでフィルタする設定)・集計基準・行
# レイアウトはこのスタイルが持つ(VW 側でユーザーが用意する)。
FOUNDATION_LEGEND_STYLE = '基礎伏図凡例'

# 各階の柱梁伏図(床伏図・小屋伏図)・母屋伏図のグラフィック凡例の構成。基礎伏図と
# 同様に、各伏図ビューポートに表示されるシンボルの凡例を各シートレイヤ上に配置する。
# ソース定義(どのビューポートのシンボルを集めるか)・集計基準・行レイアウト・行ラベルは
# ユーザーが VW 側で用意したグラフィック凡例スタイル ``床伏図凡例`` に焼き込むため、
# 命令は載せるシンボルの items を持たず(スタイルが内容を決める)、スタイルの関連付けと
# 配置だけを担う。配置点は基礎伏図と同じ既定値(VW 上で最終調整する)。
FLOOR_LEGEND_STYLE = '床伏図凡例'
FLOOR_LEGEND_POSITION = [0.0, 0.0]

# 柱梁伏図(各階)シートの構成
# タイトルの種別ラベル。一般階は "床"、最上階は主屋根の "小屋"。いずれも階番号と
# 組み合わせて "{階番号}階床" / "{階数}階小屋" のように使う。
FLOOR_PLAN_FLOOR_LABEL = '床'
FLOOR_PLAN_ROOF_LABEL = '小屋'
# 柱梁伏図のシートレイヤ番号の開始値。基礎伏図(番号 1)に続けて 2 から振る。
FLOOR_PLAN_START_NUMBER = 2

# 母屋伏図シートの構成。屋根版を持つ階(最上階の主屋根・中間階の下屋根)ごとに、
# 小屋組(母屋・垂木・野地板)を梁組と分けて表示する。柱梁伏図の最後に続けて
# シートレイヤ番号を振る。タイトルは屋根が架かる階番号を付けた "{index}階母屋伏図"。
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


def floor_plan_title(index: int, is_top: bool, count: int) -> str:
    """柱梁伏図シートのタイトルを返す。

    最上階は主屋根が架かる階番号を付けた ``{count-1}階小屋伏図``、それ以外は
    ``{index+1}階床伏図``。下屋根(下屋)の小屋組(母屋・垂木・野地板)は柱梁伏図には
    重ねず専用の母屋伏図(``build_moya_sheet_commands``)に分けるため、柱梁伏図の
    タイトルに母屋の表記は付けない。
    """
    if is_top:
        return f'{count - 1}階{FLOOR_PLAN_ROOF_LABEL}伏図'
    return f'{index + 1}階{FLOOR_PLAN_FLOOR_LABEL}伏図'


def moya_plan_title(index: int) -> str:
    """母屋伏図シートのタイトルを返す。

    屋根版を持つ階(``index``、0 起点)ごとに 1 枚。タイトルはその屋根が架かる階番号
    (0 起点 index をそのまま用いる)を付けた ``{index}階母屋伏図``。最上階(主屋根)は
    ``index = count - 1`` なので ``{count-1}階母屋伏図``(例 2 階建て=``2階母屋伏図``)、
    中間階の下屋根はその下屋が架かる階番号を付ける(例 story index 1 の下屋根=
    ``1階母屋伏図``)。
    """
    return f'{index}階{MOYA_PLAN_LABEL}伏図'


def _span_layers_at_cut(
    spans: list[tuple[float, float, str]], cut: float,
) -> list[str]:
    """span ``(from, to, layer)`` のうち切断レベル ``cut`` を含む(from ≤ cut ≤ to)
    レイヤ名を ``(from, to)`` 昇順で返す。"""
    return [
        layer for frm, to, layer in spans
        if frm <= cut <= to
    ]


def _plan_mark_layer_below_cut(
    spans: list[tuple[float, float, str]], cut: float,
) -> str | None:
    """切断レベル ``cut`` の**直下**にある伏図記号レイヤ名を返す。無ければ None。

    伏図記号は span の ``to``(span 上側の数値)をプレフィックスにした
    ``{to}-柱伏図記号`` レイヤに描かれる。伏図はその切断位置の直下(``to`` < 切断)に
    ある柱・小屋束を平面記号で示すため、``to`` < 切断を満たす span のうち **最大の
    ``to``**(切断に最も近い直下)の伏図記号レイヤ 1 つを返す。

    例: 2 階床伏図(切断 2.25)は ``to``=2 の直下柱を示す ``2-柱伏図記号``、
    1 階母屋伏図(切断 2.75)は ``to``=2.5 の下屋小屋束を示す ``2.5-柱伏図記号``。
    span の ``to`` は必ず整数(管柱・通し柱)か半整数(屋根束・小屋束)で、切断
    レベル(整数+0.25 / +0.75)とは一致しないため直下は一意に決まる。
    """
    tos = {to for _frm, to, _layer in spans if to < cut}
    if not tos:
        return None
    return plan_mark_layer_name(max(tos))


def build_floor_framing_sheet_commands(
    ifc_file: ifcopenshell.file,
    columns: list[ColumnCommand] | None = None,
) -> list[SheetCommand]:
    """各階の柱梁伏図シートの sheet 命令を組み立てて返す。

    ストーリ 1 つにつき伏図 1 枚。表示レイヤは横架材(``n-横架材天端``/最上階
    ``n-軒高``)・通り芯を基本とし、**その伏図の切断レベルを span が含む柱レイヤ**
    (``{from}to{to}-柱``)を載せる。切断レベルは ``FLOOR_PLAN_CUT_OFFSET`` により
    その階の床レベル(1 始まり=index+1)+0.25。これにより、その階を base とする柱の
    断面と、下から貫いてこの高さに達する通し柱が表示され、下屋の小屋束(to が半整数で
    その階の床に届かない)は上階の小屋伏図に写り込まない。最上階以外は床(FL)を、
    最下階には基礎がある場合にアンカーボルトを加える。

    下屋根(下屋)の小屋組(母屋・垂木・野地板)は柱梁伏図には重ねず、専用の母屋伏図
    (``build_moya_sheet_commands``)に分けて表示する(母屋等の小屋組と梁組が重なって
    見にくくなるのを防ぐ)。ストーリが無ければ空リストを返す。柱の span レイヤを切断
    レベルで絞るため column 命令(``columns``)を渡す(未指定なら内部で組み立てる)。
    """
    stories = collect_stories(ifc_file)
    foundation = has_foundation(ifc_file)
    if columns is None:
        from .column import build_column_commands
        columns = build_column_commands(ifc_file)
    spans = collect_column_spans(columns)
    commands: list[SheetCommand] = []
    n = len(stories)
    for i in range(n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        # 横架材レイヤは一般階=横架材天端、最上階=軒高。
        beam_level = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layers = [f'{prefix}-{beam_level}']
        # この伏図の切断レベル(その階の床レベル + 0.25)を span が含む柱レイヤを載せる。
        cut = i + FLOOR_PLAN_CUT_OFFSET
        layers.extend(_span_layers_at_cut(spans, cut))
        # 切断位置の直下(to < 切断)の柱・小屋束を平面記号で示す伏図記号レイヤを載せる
        # (例: 2 階床伏図=2.25 → 2-柱伏図記号)。
        mark_layer = _plan_mark_layer_below_cut(spans, cut)
        if mark_layer is not None:
            layers.append(mark_layer)
        if not is_top:
            # 最下階には基礎(アンカーボルト)がある場合に表示する。
            if i == 0 and foundation:
                layers.append(LAYER_FOUNDATION_ANCHOR)
            layers.append(f'{prefix}-{LEVEL_FL}')
        layers.append(TARGET_LAYER)
        title = floor_plan_title(i, is_top, n)
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
    columns: list[ColumnCommand] | None = None,
) -> list[SheetCommand]:
    """母屋伏図シートの sheet 命令を組み立てて返す。

    **屋根版(屋根面)を持つ階ごとに 1 枚**、その階の小屋組(母屋・垂木・野地板)を
    梁組と分けて表示する伏図を返す(複雑な下屋根では母屋等の小屋組と梁組が重なって
    見にくくなるため、柱梁伏図とは別のシート・ビューポートに分ける)。最上階(屋根)の
    主屋根だけでなく、中間階に架かる下屋根(下屋)にも 1 枚ずつ作る。シートレイヤ番号は
    各階の柱梁伏図の最後に続けて Elevation 昇順(最下階→最上階)に振る。タイトルは
    ``moya_plan_title``(``{index}階母屋伏図``)。

    表示レイヤは 母屋(``n-母屋``、母屋がある階のみ)・垂木(``n-垂木``)・野地板
    (``n-野地板``)・通り芯(``共通``)に加え、**その伏図の切断レベルを span が含む柱レイヤ**
    (``{from}to{to}-柱``)。切断レベルは ``MOYA_PLAN_CUT_OFFSET`` によりその階の床レベル
    (1 始まり=index+1)+0.75。これにより、屋根を貫いて立ち上がる主屋の柱(管柱・通し柱、
    例 ``2to3``・``1to3``)が表示され、母屋を支える小屋束(span の to が半整数で切断より
    低い、例 ``2to2.5``)は表示されない(母屋伏図は母屋の上からの見下げ図なので小屋束の
    断面は出さず、小屋束の位置は平面の伏図記号で示す=span 方式への移行後に別途対応)。

    下屋根は母屋を持たない(単純な片流れ等)こともあるため、母屋レイヤは母屋がある階
    (``moya_flags``)にだけ加え、垂木・野地板は屋根版がある階(``roof_flags``)に加える。
    柱の span レイヤを切断レベルで絞るため column 命令(``columns``)を渡す(未指定なら
    内部で組み立てる)。ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    if not stories:
        return []
    if columns is None:
        from .column import build_column_commands
        columns = build_column_commands(ifc_file)
    spans = collect_column_spans(columns)
    moya_flags = collect_story_moya_flags(ifc_file)
    roof_flags = collect_story_roof_flags(ifc_file)
    n = len(stories)
    # 番号の開始値: 基礎伏図(1)+各階柱梁伏図(ストーリ数)の次
    base_number = FLOOR_PLAN_START_NUMBER + n
    commands: list[SheetCommand] = []
    seq = 0
    for i in range(n):
        is_top = i == n - 1
        # 屋根版を持つ階(最上階の主屋根・中間階の下屋根)だけ母屋伏図を作る。
        if not (is_top or roof_flags[i]):
            continue
        prefix = layer_prefix_for(i, is_top)
        layers: list[str] = []
        # 母屋は母屋がある階のみ(片流れ下屋等は母屋を持たず垂木・野地板だけ)。
        if is_top or moya_flags[i]:
            layers.append(f'{prefix}-{LEVEL_MOYA}')
        layers.append(f'{prefix}-{LEVEL_TARUKI}')
        layers.append(f'{prefix}-{LEVEL_NOJIITA}')
        # この伏図の切断レベル(その階の床レベル + 0.75)を span が含む柱レイヤを載せる。
        cut = i + MOYA_PLAN_CUT_OFFSET
        layers.extend(_span_layers_at_cut(spans, cut))
        # 切断位置の直下(to < 切断)の柱・小屋束を平面記号で示す伏図記号レイヤを載せる
        # (例: 1 階母屋伏図=2.75 → 2.5-柱伏図記号)。
        mark_layer = _plan_mark_layer_below_cut(spans, cut)
        if mark_layer is not None:
            layers.append(mark_layer)
        layers.append(TARGET_LAYER)
        title = moya_plan_title(i)
        number = str(base_number + seq)
        seq += 1
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
        'style': FOUNDATION_LEGEND_STYLE,
        'position': list(FOUNDATION_LEGEND_POSITION),
        'items': items,
    }]


def build_floor_legend_commands(
    ifc_file: ifcopenshell.file,
    columns: list[ColumnCommand] | None = None,
) -> list[LegendCommand]:
    """各階の柱梁伏図・母屋伏図のグラフィック凡例の legend 命令を組み立てて返す。

    基礎伏図(``build_legend_commands``)と同様に、**各柱梁伏図(床伏図・小屋伏図)と
    各母屋伏図のシートレイヤ**にグラフィック凡例を 1 つずつ配置する。凡例に載せる
    シンボルとラベル(ソース定義・集計基準・行レイアウト)はユーザーが VW 側で用意した
    グラフィック凡例スタイル ``床伏図凡例``(``FLOOR_LEGEND_STYLE``)に焼き込むため、
    命令は ``items`` を持たず(スタイルが内容を決める)、スタイルの関連付けと配置だけを
    担う(基礎伏図が ``基礎伏図凡例`` を関連付けるのと同じプラグインスタイル方式)。

    配置先シートレイヤ番号は柱梁伏図・母屋伏図の sheet 命令(``number``)と一致させる
    ため、それぞれの sheet 命令を組み立てて番号を引く。柱の span レイヤを切断レベルで
    絞るため column 命令(``columns``)を渡す(未指定なら sheet 側で組み立てる)。伏図が
    1 枚も無ければ空リストを返す。
    """
    sheets = [
        *build_floor_framing_sheet_commands(ifc_file, columns),
        *build_moya_sheet_commands(ifc_file, columns),
    ]
    return [{
        'number': sheet['number'],
        'style': FLOOR_LEGEND_STYLE,
        'position': list(FLOOR_LEGEND_POSITION),
        'items': [],
    } for sheet in sheets]


def build_sheet_commands(
    ifc_file: ifcopenshell.file,
    columns: list[ColumnCommand] | None = None,
) -> list[SheetCommand]:
    """sheet 命令のリストを組み立てて返す。

    基礎伏図(基礎がある場合のみ)に続けて、各階の柱梁伏図、最後に母屋伏図を
    組み立てる。柱梁伏図・母屋伏図はともに柱の span レイヤを切断レベルで絞るため
    columns を渡す(未指定なら内部で組み立てる)。
    """
    return [
        *build_foundation_sheet_commands(ifc_file),
        *build_floor_framing_sheet_commands(ifc_file, columns),
        *build_moya_sheet_commands(ifc_file, columns),
    ]
