"""柱 (IfcColumn) の解析と column 命令の組み立て。vs 非依存。

IFC の IfcColumn を走査し、各階の横架材天端レイヤ（最上階は軒高レイヤ）に
配置する column 命令を生成する。断面寸法（幅・成）と柱高さは押し出しソリッド
から取得し、配置 Z はストーリ高さに柱のローカル配置 Z を加えた絶対値を使う。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnCommand, StoryBound
from .grid import resolve_lines
from .member import _get_profile_dims
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_COLUMN,
    LEVEL_COLUMN_PLAN,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
    resolve_beam_top_offset,
)

if TYPE_CHECKING:
    import ifcopenshell

# IfcColumn.ObjectType から木造BIM 柱・間柱ツールの種別名へのマッピング。
# ホームズ君 IFC では ObjectType は None（管柱）または "STANDCOLUMN"（小屋束）。
# ツールの種別ドロップダウンの有効値は 管柱 / 通し柱 / 間柱 / 小屋束 / 吊木。
DEFAULT_COLUMN_TYPE = '管柱'
COLUMN_TYPE_BY_OBJECT_TYPE = {
    'STANDCOLUMN': '小屋束',
}


def resolve_column_type(object_type: str | None) -> str:
    """IfcColumn.ObjectType を柱・間柱ツールの種別名に変換する。

    未知の ObjectType（None 含む）は既定種別（管柱）として扱う。
    """
    if object_type is None:
        return DEFAULT_COLUMN_TYPE
    return COLUMN_TYPE_BY_OBJECT_TYPE.get(object_type, DEFAULT_COLUMN_TYPE)


def _get_position_2d(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float] | None:
    """IfcProduct のローカル配置から 2D 配置座標 (ox, oy) を返す。

    取得できない場合は None を返す。ホームズ君 IFC ではストーリの XY 原点が
    (0, 0) のため、ローカル配置 Location の XY をそのまま平面座標として扱える
    （横架材と同じ座標系・グリッド中心オフセットで補正できる）。
    """
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None or not placement.is_a('IfcLocalPlacement'):
        return None
    rel = placement.RelativePlacement
    if rel is None or not rel.is_a('IfcAxis2Placement3D'):
        return None
    loc = rel.Location
    if loc is None:
        return None
    coords = loc.Coordinates
    if len(coords) < 2:
        return None
    return float(coords[0]), float(coords[1])


def _base_level(
    index: int, top_idx: int, elevations: list[float], beam_offsets: list[float],
) -> tuple[str, float]:
    """階 index の「基準レベル」(柱を配置するレイヤのレベル) を返す。

    Returns: (level_type, base_absolute)
        一般階は横架材天端 (FL からの負オフセット)、最上階は軒高 (オフセット 0)。
        base_absolute はそのレベルの絶対 Z (= storey_elevation + base_offset)。
    """
    if index == top_idx:
        return LEVEL_EAVES, elevations[index]
    return LEVEL_BEAM_TOP, elevations[index] + beam_offsets[index]


def build_column_commands(ifc_file: ifcopenshell.file) -> list[ColumnCommand]:
    """IFC の柱から column 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    柱は各階の柱レイヤ（``n-柱``）に配置し、柱・間柱ツールの伏図記号は
    伏図レイヤ（``n-柱(伏図)``）に描く。高さ基準（横架材天端／軒高）は
    レベルタイプとして引き続き参照する。

    柱高さは固定値ではなく上下端をストーリレベル基準で指定する
    （高さ基準(下)=当該階の横架材天端、高さ基準(上)=上階の横架材天端 or 軒高）。
    オフセットは IFC 上の絶対高さに合わせ、階高変更に追従できるようにする。
    最上階（上階が存在しない）の柱は上下端とも当該階の軒高を基準にする。
    """
    _, center_x, center_y = resolve_lines(ifc_file)

    storeys = sorted(
        [s for s in ifc_file.by_type('IfcBuildingStorey')
         if (s.Name or '').upper().endswith('FL')],
        key=lambda s: float(s.Elevation or 0.0),
    )
    if not storeys:
        return []

    top_idx = len(storeys) - 1
    elevations = [float(s.Elevation or 0.0) for s in storeys]
    beam_offsets = [resolve_beam_top_offset(s) for s in storeys]

    commands: list[ColumnCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 柱は各階の柱レイヤに配置し、伏図記号は伏図レイヤに描く
        layer_name = f'{prefix}-{LEVEL_COLUMN}'
        plan_layer_name = f'{prefix}-{LEVEL_COLUMN_PLAN}'

        storey_elevation = elevations[i]
        base_level_type, base_abs = _base_level(
            i, top_idx, elevations, beam_offsets)

        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not element.is_a('IfcColumn'):
                    continue

                position = _get_position_2d(element)
                if position is None:
                    continue
                dims = _get_profile_dims(element)
                if dims is None:
                    continue

                ox, oy = position
                # 押し出し: XDim=幅, YDim=成, Depth=柱高さ
                width, depth, height = dims

                local_z = get_local_placement_z(element) or 0.0
                bottom_abs = storey_elevation + local_z
                top_abs = bottom_abs + height

                # 高さ基準(下): 当該階の基準レベル (横架材天端 or 軒高)
                bottom_bound: StoryBound = {
                    'story': 0,
                    'level': base_level_type,
                    'offset': bottom_abs - base_abs,
                }

                # 高さ基準(上): 上階の横架材天端 or 軒高。上階が無ければ当該階の軒高。
                if i < top_idx:
                    upper = i + 1
                    if upper == top_idx:
                        upper_level_type, upper_abs = LEVEL_EAVES, elevations[upper]
                    else:
                        upper_level_type = LEVEL_BEAM_TOP
                        upper_abs = elevations[upper] + beam_offsets[upper]
                    top_bound: StoryBound = {
                        'story': 1,
                        'level': upper_level_type,
                        'offset': top_abs - upper_abs,
                    }
                else:
                    top_bound = {
                        'story': 0,
                        'level': LEVEL_EAVES,
                        'offset': top_abs - base_abs,
                    }

                commands.append({
                    'layer': layer_name,
                    'plan_layer': plan_layer_name,
                    'column_type': resolve_column_type(element.ObjectType),
                    'position': [ox - center_x, oy - center_y],
                    'width': width,
                    'depth': depth,
                    'height': height,
                    'elevation': bottom_abs,
                    'bottom_bound': bottom_bound,
                    'top_bound': top_bound,
                })

    return commands
