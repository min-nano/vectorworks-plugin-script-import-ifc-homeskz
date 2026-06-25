"""ストーリ (IfcBuildingStorey) の解析と story 命令の組み立て。vs 非依存。

ホームズ君 IFC の高さ表現ルールを利用してストーリを構築する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import LevelCommand, StoryCommand

if TYPE_CHECKING:
    import ifcopenshell

LEVEL_FL = 'FL'
LEVEL_BEAM_TOP = '横架材天端'
LEVEL_EAVES = '軒高'
LEVEL_COLUMN = '柱'
STORY_ROOF = '屋根'


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
    さらに各階に柱配置用の 柱 レベル(オフセットは横架材天端と同じ=最上階は軒高)
    を加える。柱は 柱 レイヤに梁と同じ構造材ツールで配置する。
    """
    stories = collect_stories(ifc_file)

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
        # 柱を配置するレイヤ。高さは横架材天端(最上階は軒高)に揃える。
        # レベルの並び順がデザインレイヤのスタック順(ナビゲーション表示順)になるため、
        # 柱レイヤが FL(最上階は軒高)レイヤの直上に来るよう先頭に挿入する。
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
