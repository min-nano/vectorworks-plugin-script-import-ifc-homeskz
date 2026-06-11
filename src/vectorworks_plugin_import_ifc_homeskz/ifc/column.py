"""柱 (IfcColumn) の解析と column 命令の組み立て。vs 非依存。

IFC の IfcColumn を走査し、各階の横架材天端レイヤ（最上階は軒高レイヤ）に
配置する column 命令を生成する。断面寸法（幅・成）と柱高さは押し出しソリッド
から取得し、配置 Z はストーリ高さに柱のローカル配置 Z を加えた絶対値を使う。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnCommand
from .grid import resolve_lines
from .member import _get_profile_dims
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
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


def build_column_commands(ifc_file: ifcopenshell.file) -> list[ColumnCommand]:
    """IFC の柱から column 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    一般階は横架材天端レイヤ、最上階（屋根）は軒高レイヤを指定する
    （横架材と同じレイヤ割り当て規則）。
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
    commands: list[ColumnCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 最上階は横架材天端レイヤがなく軒高レイヤに配置する
        layer_suffix = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layer_name = f'{prefix}-{layer_suffix}'

        storey_elevation = float(storey.Elevation or 0.0)

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

                local_z = get_local_placement_z(element)
                elevation = storey_elevation + (local_z if local_z is not None else 0.0)

                commands.append({
                    'layer': layer_name,
                    'column_type': resolve_column_type(element.ObjectType),
                    'position': [ox - center_x, oy - center_y],
                    'width': width,
                    'depth': depth,
                    'height': height,
                    'elevation': elevation,
                })

    return commands
