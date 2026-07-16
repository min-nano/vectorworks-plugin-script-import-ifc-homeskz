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
LEVEL_COLUMN = '柱'
# 母屋(棟木を含む小屋組の上端材)を配置するレイヤ・レベル。最上階(屋根)で
# 梁(小屋梁・軒桁)と重なって見にくいため、軒高レイヤと分けた専用レイヤに置く。
LEVEL_MOYA = '母屋'
# 下階柱記号(柱束伏図記号 PIO)を配置するレイヤ・レベル。各階の伏図に直下階
# (N-1)の柱を記号化するため、横架材天端(最上階は軒高)レイヤの直上に積む。
LEVEL_UNDER_COLUMN = '下階柱'
# 小屋束の伏図記号(柱束伏図記号 PIO)を配置するレイヤ・レベル。最上階(屋根)の
# 小屋束を母屋伏図に記号化するため、母屋レイヤの直上に専用レイヤを積む。柱の下階柱
# 記号とはクラスで分けた別オブジェクトにする(小屋束記号節参照)。最上階のみ持つ。
LEVEL_KOYAZUKA_MARK = '小屋束'
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


def build_story_commands(ifc_file: ifcopenshell.file) -> list[StoryCommand]:
    """IFC のストーリから story 命令のリストを組み立てる。

    一般階は FL(0) と 横架材天端(負オフセット)、最上階は 軒高(0) を構造レベルとし、
    さらに各階に柱配置用の 柱 レベル(高さは横架材天端=最上階は軒高に揃える)を加える。
    柱は 柱 レイヤに梁と同じ構造材ツールで配置する。

    加えて最下階(下に柱が無い)以外の各階には、直下階(N-1)の柱を伏図に記号化する
    下階柱記号(柱束伏図記号 PIO)を置く 下階柱 レベルを、横架材天端(最上階は軒高)
    レイヤの直上に積む。母屋(棟木含む)を梁と分けて配置する 母屋 レベルは、最上階
    (屋根)は常に、中間階は下屋根(下屋)の小屋組を名前判定(``story_has_moya`` /
    ``collect_story_moya_flags``)で含む場合に、横架材天端(最上階は軒高)レイヤの
    直上に積む。最上階はさらにその母屋レイヤの直上に小屋束を母屋伏図へ記号化する
    小屋束 レベル(柱束伏図記号 PIO の配置先)を積む(中間階の下屋根には付けない)。

    ``levels`` の並び順は**デザインレイヤの希望スタック順(上→下)**を表す。柱レイヤを
    FL(最上階は軒高)レイヤの直上に積むため 柱 レベルを先頭に置く。実際のレイヤ並びは
    描画フェーズ(vw.story)が HMoveForward で命令の順序どおりに揃える(レイヤの高さ
    オフセットに依存しない)。
    """
    stories = collect_stories(ifc_file)
    moya_flags = collect_story_moya_flags(ifc_file)

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
        # 下階柱記号のレイヤ。直下階(N-1)の柱を伏図に記号化するため、横架材天端
        # (最上階は軒高)レイヤの**直上**に積む(levels の末尾=横架材天端/軒高の
        # 直前に挿入する)。最下階(i=0)は下に柱が無いため作らない。高さは横架材天端
        # (最上階は軒高)に揃える。
        if i >= 1:
            levels.insert(
                len(levels) - 1,
                {'type': LEVEL_UNDER_COLUMN, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_UNDER_COLUMN}'})
        # 母屋(棟木含む)を配置するレイヤ。最上階(屋根)は常に、中間階は下屋根の
        # 小屋組(母屋・棟木)を含む場合に、横架材天端(最上階は軒高)レイヤの直上に
        # 積む(levels の末尾=横架材天端/軒高の直前に挿入する)。高さは横架材天端
        # (最上階は軒高)に揃える(offset=column_offset。最上階は 0)ため実描画の
        # 高さは母屋部材の天端バインドが担い、この offset には依存しない。加えて
        # 最上階(屋根)は母屋伏図に小屋束を記号化する小屋束記号レイヤ(母屋レイヤの
        # 直上)も積む(中間階の下屋根には小屋束記号を付けない)。
        if is_top or moya_flags[i]:
            levels.insert(
                len(levels) - 1,
                {'type': LEVEL_MOYA, 'offset': column_offset,
                 'layer': f'{prefix}-{LEVEL_MOYA}'})
            if is_top:
                levels.insert(
                    len(levels) - 2,
                    {'type': LEVEL_KOYAZUKA_MARK, 'offset': 0.0,
                     'layer': f'{prefix}-{LEVEL_KOYAZUKA_MARK}'})
        # 柱を配置するレイヤ。高さは横架材天端(最上階は軒高)に揃える。
        # levels の先頭=スタック最上段とし、FL(最上階は軒高)レイヤの直上に来るようにする。
        levels.insert(
            0,
            {'type': LEVEL_COLUMN, 'offset': column_offset,
             'layer': f'{prefix}-{LEVEL_COLUMN}'})
        commands.append({
            'name': story_name_for(i, is_top),
            'suffix': story_suffix_for(i, is_top),
            'elevation': elevation,
            'levels': levels,
        })
    return commands
