"""ストーリ (IfcBuildingStorey) の解析と story 命令の組み立て。vs 非依存。

ホームズ君 IFC の高さ表現ルールを利用してストーリを構築する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import LevelCommand, StoryCommand
from .structural_class import CLASS_MOYA, CLASS_MUNAGI, member_class_from_name

if TYPE_CHECKING:
    import ifcopenshell

LEVEL_FL = 'FL'
LEVEL_BEAM_TOP = '横架材天端'
LEVEL_EAVES = '軒高'
# 柱・小屋束は span(またぐレベル区間)ごとに専用レイヤ ``{from}to{to}-柱`` に
# 配置する。from は柱が立つ床レベル(1 始まり・GL=0)、to は上端が届く床/母屋
# レベル。管柱は次階に達して整数、小屋束・屋根束は屋根面で止まって半整数(+0.5)、
# 通し柱は複数階ぶん上の床に達する。各伏図はその切断レベルを span が含むレイヤ
# だけを表示するため、下屋の小屋束(例 ``2to2.5``)が上階の小屋伏図(切断 3.25)に
# 写り込まなくなる。
LAYER_COLUMN_SUFFIX = '柱'


def _fmt_span_level(value: float) -> str:
    """span レベルを文字列にする(整数は小数点なし、半整数は ``.5`` 付き)。"""
    if value == int(value):
        return str(int(value))
    return str(value)


def span_layer_name(from_level: float, to_level: float) -> str:
    """柱の span からデザインレイヤ名 ``{from}to{to}-柱`` を作る。"""
    return f'{_fmt_span_level(from_level)}to{_fmt_span_level(to_level)}-{LAYER_COLUMN_SUFFIX}'


def parse_span_layer(name: str) -> tuple[float, float] | None:
    """``{from}to{to}-柱`` レイヤ名を (from, to) に分解する。span 柱レイヤでなければ None。"""
    suffix = f'-{LAYER_COLUMN_SUFFIX}'
    if not name.endswith(suffix):
        return None
    core = name[: -len(suffix)]
    parts = core.split('to')
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


# 柱・小屋束の伏図記号(平面記号)を配置する専用レイヤの接尾辞。伏図記号は
# span 柱レイヤの **span 上側の数値(to)** をプレフィックスにした ``{to}-柱伏図記号``
# レイヤに描く(例 ``1to2.5-柱`` と ``2to2.5-柱`` の伏図記号はともに ``2.5-柱伏図記号``)。
# 通り芯(``共通``)と同じくストーリに縛られない独立したデザインレイヤで、``共通`` の
# 直下(スタック上段)に積む。各伏図は切断位置の直下(``to`` < 切断)の伏図記号レイヤ
# だけを表示する(``ifc/sheet.py``)。
LAYER_PLAN_MARK_SUFFIX = '柱伏図記号'


def plan_mark_layer_name(to_level: float) -> str:
    """span の ``to`` レベルから伏図記号レイヤ名 ``{to}-柱伏図記号`` を作る。"""
    return f'{_fmt_span_level(to_level)}-{LAYER_PLAN_MARK_SUFFIX}'
# 母屋(棟木を含む小屋組の上端材)を配置するレイヤ・レベル。最上階(屋根)で
# 梁(小屋梁・軒桁)と重なって見にくいため、軒高レイヤと分けた専用レイヤに置く。
LEVEL_MOYA = '母屋'
# 垂木を配置するレイヤ・レベル。垂木は屋根版(屋根面)の勾配・外形から導出し、
# 母屋の上に載る。母屋・棟木と重ならないよう母屋レイヤの直上に独立させて積む。
# 高さは母屋(横架材天端/軒高)に揃える(実描画の Z は屋根版由来の絶対値で
# FramingMember に持たせるためレベルのオフセットには依存しない)。
LEVEL_TARUKI = '垂木'
# 野地板(屋根の下地合板)を配置するレイヤ・レベル。野地板は屋根版(屋根面)の
# 勾配・外形から屋根ツール(BeginRoof)で描き、垂木の上に載る。垂木と重ならない
# よう垂木レイヤの直上に独立させて積む。高さは垂木(横架材天端/軒高)に揃える
# (実描画の Z は屋根版由来の絶対値で屋根オブジェクトが持つためオフセットには依存しない)。
LEVEL_NOJIITA = '野地板'
STORY_ROOF = '屋根'

# 基礎(立上り・底盤・アンカーボルト)用のストーリ・レベル・レイヤ
STORY_FOUNDATION = '基礎'
FOUNDATION_SUFFIX = 'F'
LEVEL_GL = 'GL'
LEVEL_SLAB_TOP = '底盤天端'
LEVEL_FOUNDATION_TOP = '基礎天端'  # アンカーボルトの高さ基準(立上り天端)
# 床束(シンボル)を配置するレベル・レイヤ。床束は基礎底盤上端(底盤天端)に立つ
# ため高さは底盤天端に揃える。底盤(F-底盤)と分けた専用レイヤに置く。
LEVEL_FLOOR_POST = '床束'
LAYER_FOUNDATION_WALL = f'{FOUNDATION_SUFFIX}-立上り'
LAYER_FOUNDATION_SLAB = f'{FOUNDATION_SUFFIX}-底盤'
LAYER_FOUNDATION_ANCHOR = f'{FOUNDATION_SUFFIX}-アンカーボルト'
LAYER_FOUNDATION_FLOOR_POST = f'{FOUNDATION_SUFFIX}-床束'


def get_local_placement_z(element: ifcopenshell.entity_instance) -> float | None:
    """IfcProduct のローカル配置 Z 座標 (浮動小数点) を取得する。取得できない場合は None。"""
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None or not placement.is_a('IfcLocalPlacement'):
        return None
    rel = placement.RelativePlacement
    if rel is None or not rel.is_a('IfcAxis2Placement3D'):
        return None
    loc = rel.Location
    if loc is None or not loc.is_a('IfcCartesianPoint'):
        return None
    coords = loc.Coordinates
    if len(coords) < 3:
        return None
    return float(coords[2])


def resolve_beam_top_offset(storey: ifcopenshell.entity_instance) -> float:
    """階に属する IfcColumn または IfcSlab から横架材天端の相対オフセット (FL からの負値) を求める。

    IFC のローカル配置 Z 座標が負の柱・床版のうち最大値(床に最も近接したオフセット)を返す。
    最初に見つかった値ではなく最大値を使うことで、IFC ファイル内の
    エンティティ列挙順に依存しない決定的な結果になり、かつ床に最も近い横架材天端を採用できる。
    見つからなければ 0.0 を返す。
    """
    offsets: list[float] = []
    for rel in storey.ContainsElements or ():
        for element in rel.RelatedElements:
            if not (element.is_a('IfcColumn') or element.is_a('IfcSlab')):
                continue
            z = get_local_placement_z(element)
            if z is not None and z < 0:
                offsets.append(z)
    return max(offsets, default=0.0)


def story_has_moya(storey: ifcopenshell.entity_instance) -> bool:
    """階に属する横架材の ``Name`` から母屋・棟木(小屋組)を含むか判定する。

    中間階に架かる下屋根(下屋)の小屋組は、その階の IfcBeam/IfcMember の
    ``Name`` が母屋・棟木に対応するもの(``member_class_from_name`` が
    ``CLASS_MOYA`` / ``CLASS_MUNAGI`` を返すもの)として表れる。1 つでもあれば
    True を返す。この判定は横架材の描画側(``ifc/member.py`` の母屋レイヤ振り分け)
    が中間階の母屋を専用レイヤ(``n-母屋``)に置く条件と一致させる必要がある。
    """
    for rel in storey.ContainsElements or ():
        for element in rel.RelatedElements:
            if not (element.is_a('IfcBeam') or element.is_a('IfcMember')):
                continue
            if member_class_from_name(element.Name) in (CLASS_MOYA, CLASS_MUNAGI):
                return True
    return False


def story_has_roof(storey: ifcopenshell.entity_instance) -> bool:
    """階に属する IfcSlab から屋根面(``屋根版``)を含むか判定する。

    垂木は屋根版(屋根面)から導出するため、屋根版を含む階は垂木レイヤ(``n-垂木``)
    を持つ。中間階に架かる下屋根(下屋)は母屋を持たないこともある(単純な片流れ
    下屋等)ため、垂木レイヤの有無は母屋(``story_has_moya``)ではなく屋根版の有無で
    判定する。1 つでもあれば True を返す。この判定は垂木の描画側(``ifc/rafter.py``)
    が屋根版から垂木を配置する階と一致させる必要がある。
    """
    for rel in storey.ContainsElements or ():
        for element in rel.RelatedElements:
            if element.is_a('IfcSlab') and (element.Name or '').startswith('屋根版'):
                return True
    return False


def collect_story_roof_flags(ifc_file: ifcopenshell.file) -> list[bool]:
    """``collect_stories`` と同じ Elevation 昇順で、各階が屋根版を含むか返す。

    各要素は ``story_has_roof`` による判定の結果。屋根版を含む階は垂木レイヤ
    (``n-垂木``)を持つ。最上階(屋根)は主屋根の屋根版を必ず含むが、判定は
    ``is_top`` でも保証する(build_story_commands 参照)。
    """
    storeys = [
        s for s in ifc_file.by_type('IfcBuildingStorey')
        if (s.Name or '').upper().endswith('FL')
    ]
    storeys.sort(key=lambda s: float(s.Elevation or 0.0))
    return [story_has_roof(s) for s in storeys]


def collect_story_moya_flags(ifc_file: ifcopenshell.file) -> list[bool]:
    """``collect_stories`` と同じ Elevation 昇順で、各階が母屋(小屋組)を含むか返す。

    各要素は ``story_has_moya`` による名前判定の結果。最上階(屋根)は母屋を必ず
    専用レイヤ(``R-母屋``)・専用シート(母屋伏図)へ分離するため、この判定とは
    別に描画側が常に母屋レイヤを持つが、下屋の小屋組を持つ中間階は名前判定で
    母屋レイヤを追加するかどうかを決める。
    """
    storeys = [
        s for s in ifc_file.by_type('IfcBuildingStorey')
        if (s.Name or '').upper().endswith('FL')
    ]
    storeys.sort(key=lambda s: float(s.Elevation or 0.0))
    return [story_has_moya(s) for s in storeys]


def collect_stories(ifc_file: ifcopenshell.file) -> list[tuple[float, float | None]]:
    """IFC からストーリ情報を集める。

    Returns: [(elevation, beam_offset_or_None), ...] を Elevation 昇順で返す。
        最上階は beam_offset=None (軒高のみ)、それ以外は beam_offset=負値 (横架材天端の FL からのオフセット)。

    名前が "FL" で終わらないストーリ (例: 設計GL) は地盤レベル等の参照高であり VW のストーリには
    しないため除外する。これを残すと既定高さ 0 のストーリが複数できて CreateStory が衝突する。
    """
    storeys = [
        s for s in ifc_file.by_type('IfcBuildingStorey')
        if (s.Name or '').upper().endswith('FL')
    ]
    storeys.sort(key=lambda s: float(s.Elevation or 0.0))
    result: list[tuple[float, float | None]] = []
    for i, storey in enumerate(storeys):
        elev = float(storey.Elevation or 0.0)
        if i == len(storeys) - 1:
            result.append((elev, None))
        else:
            result.append((elev, resolve_beam_top_offset(storey)))
    return result


def story_name_for(index: int, is_top: bool) -> str:
    """index (0-origin) と最上階フラグから VectorWorks のストーリ名を返す。"""
    return STORY_ROOF if is_top else f'{index + 1}階'


def story_suffix_for(index: int, is_top: bool) -> str:
    """CreateStory の suffix (前/後 記号) を返す。

    非空文字でないと 2 回目以降の CreateStory が失敗する。
    建築慣例の階表記に合わせ、一般階は階番号 ("1", "2", ...)、最上階は "R" (Roof)。
    """
    return 'R' if is_top else str(index + 1)


def layer_prefix_for(index: int, is_top: bool) -> str:
    """デザインレイヤ名の接頭辞を返す (ストーリ suffix と同じ "1"/"2"/"R")。"""
    return story_suffix_for(index, is_top)


def build_story_commands(
    ifc_file: ifcopenshell.file,
    column_layers_by_story: dict[int, list[str]] | None = None,
) -> list[StoryCommand]:
    """IFC のストーリから story 命令のリストを組み立てる。

    一般階は FL(0) と 横架材天端(負オフセット)、最上階は 軒高(0) を構造レベルとし、
    さらに各階に柱・小屋束を配置する **span レベル**(``{from}to{to}-柱`` レイヤ。
    ``column_layers_by_story`` がその階を base=from とする span レイヤを (from, to) 昇順で
    渡す)を、高さを横架材天端(最上階は軒高)に揃えて加える。span レベルの type はレイヤ名
    (一意)。span 方式では従来の 下階柱記号・小屋束記号(平面伏図記号)レベルは廃止した
    (柱の表示は伏図の切断レベルで制御する。母屋伏図向けの小屋束伏図記号は移行後に別途対応)。

    母屋(棟木含む)を梁と分けて配置する 母屋 レベルは、最上階(屋根)は常に、中間階は
    下屋根(下屋)の小屋組を名前判定(``story_has_moya`` / ``collect_story_moya_flags``)で
    含む場合に、横架材天端(最上階は軒高)レイヤの直上に積む。垂木・野地板の各レベルは、
    最上階(屋根)は常に、中間階は屋根版(屋根面)を含む場合に、母屋レイヤの直上に積む
    (下屋根は母屋を持たなくても屋根版があれば垂木・野地板を持つ)。

    ``levels`` の並び順は**デザインレイヤの希望スタック順(上→下)**を表す。span 柱レイヤを
    FL(最上階は軒高)レイヤの直上に積むため span レベルを先頭に置く。実際のレイヤ並びは
    描画フェーズ(vw.story)が HMoveForward で命令の順序どおりに揃える(レイヤの高さ
    オフセットに依存しない)。span レイヤは実在する柱から決まるため未指定なら遅延 import で
    組み立てる(story→column の循環 import を避けるため関数内 import)。
    """
    stories = collect_stories(ifc_file)
    moya_flags = collect_story_moya_flags(ifc_file)
    roof_flags = collect_story_roof_flags(ifc_file)
    # 柱は span(またぐレベル区間)ごとの専用レイヤ ``{from}to{to}-柱`` に配置する。
    # 各ストーリに載せる span レイヤは実在する柱から決まるため、未指定なら遅延 import で
    # 組み立てる(story→column の循環 import を避けるため関数内 import)。
    if column_layers_by_story is None:
        from .column import build_column_commands, collect_column_layers_by_story
        column_layers_by_story = collect_column_layers_by_story(
            build_column_commands(ifc_file))

    commands: list[StoryCommand] = []
    n = len(stories)
    for i, (elevation, beam_offset) in enumerate(stories):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        if is_top:
            # 最上階の柱配置基準は軒高(オフセット 0)
            column_offset = 0.0
            levels: list[LevelCommand] = [
                {'type': LEVEL_EAVES, 'offset': 0.0, 'layer': f'{prefix}-{LEVEL_EAVES}'},
            ]
        else:
            # 最上階以外では collect_stories が必ず float を返す
            column_offset = beam_offset if beam_offset is not None else 0.0
            levels = [
                {'type': LEVEL_FL, 'offset': 0.0, 'layer': f'{prefix}-{LEVEL_FL}'},
                {'type': LEVEL_BEAM_TOP, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_BEAM_TOP}'},
            ]
        # 小屋組の上端材(母屋・棟木)・垂木・野地板を横架材天端(最上階は軒高)レイヤの
        # 直上に積む。母屋レイヤは最上階(屋根)は常に、中間階は下屋根の小屋組(母屋・棟木)
        # を名前判定で含む場合に持つ。垂木・野地板レイヤは最上階は常に、中間階は屋根版
        # (屋根面)を含む場合に持つ(下屋根は母屋を持たなくても屋根版=垂木・野地板が
        # あるため、母屋とは別に屋根版の有無で判定する)。スタックは 横架材天端/軒高 ←
        # 母屋 ← 垂木 ← 野地板(上ほど上段)で、垂木を母屋の直上、野地板を垂木の直上に積む
        # (母屋が無ければ横架材天端/軒高の直上)。高さはいずれも横架材天端(最上階は軒高)
        # に揃える(offset=column_offset。最上階は 0)ため実描画の高さは母屋・垂木・野地板の
        # 要素が持ち、この offset には依存しない。
        tail = len(levels) - 1  # FL(最上階は軒高)/横架材天端 の位置(この直前に挿入)
        if is_top or moya_flags[i]:
            levels.insert(
                tail,
                {'type': LEVEL_MOYA, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_MOYA}'})
        if is_top or roof_flags[i]:
            levels.insert(
                tail,
                {'type': LEVEL_TARUKI, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_TARUKI}'})
            # 野地板は垂木の直上(垂木の後に tail へ挿入して 1 段上に積む)。
            levels.insert(
                tail,
                {'type': LEVEL_NOJIITA, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_NOJIITA}'})
        # 柱を配置する span レイヤ(``{from}to{to}-柱``)。この階を base(from=i+1)とする
        # span を (from, to) 昇順で levels の先頭=スタック最上段に積む(FL/軒高レイヤの
        # 直上)。高さは横架材天端(最上階は軒高)に揃える(柱の上下端はバインド先レベルで
        # 決まりこの offset には依存しない)。level type はレイヤ名と同じ一意な文字列にする。
        for layer in reversed(column_layers_by_story.get(i, [])):
            levels.insert(
                0,
                {'type': layer, 'offset': column_offset, 'layer': layer})
        commands.append({
            'name': story_name_for(i, is_top),
            'suffix': story_suffix_for(i, is_top),
            'elevation': elevation,
            'levels': levels,
        })
    return commands
