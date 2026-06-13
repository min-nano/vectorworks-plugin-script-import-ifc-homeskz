"""通り芯 (IfcGridAxis) の解析と grid 命令の組み立て。vs 非依存。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import GridCommand

if TYPE_CHECKING:
    import ifcopenshell

CLASS_X = '01作図-01線-01基準線-01通り芯-X通り'
CLASS_Y = '01作図-01線-01基準線-01通り芯-Y通り'
TARGET_LAYER = '共通'

# (x1, y1, x2, y2, 軸名)
Line = tuple[float, float, float, float, str]


def resolve_lines(ifc_file: ifcopenshell.file) -> tuple[list[Line], float, float]:
    """IfcGridAxis エンティティを座標に解決し (lines_to_draw, center_x, center_y) を返す。

    lines_to_draw: [(x1, y1, x2, y2, name), ...]
    """
    lines_to_draw: list[Line] = []
    drawn_keys: set[tuple[tuple[float, float], ...]] = set()

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')

    for axis in ifc_file.by_type('IfcGridAxis'):
        name = axis.AxisTag or ''
        curve = axis.AxisCurve
        if curve is None or not curve.is_a('IfcPolyline'):
            continue

        pts = [(float(pt.Coordinates[0]), float(pt.Coordinates[1])) for pt in curve.Points]

        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]

            line_key = tuple(sorted(((x1, y1), (x2, y2))))
            if line_key in drawn_keys:
                continue
            drawn_keys.add(line_key)

            min_x = min(min_x, x1, x2)
            max_x = max(max_x, x1, x2)
            min_y = min(min_y, y1, y2)
            max_y = max(max_y, y1, y2)

            lines_to_draw.append((x1, y1, x2, y2, name))

    if lines_to_draw:
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
    else:
        center_x = 0.0
        center_y = 0.0

    return lines_to_draw, center_x, center_y


def determine_class(name: str, cx1: float, cy1: float, cx2: float, cy2: float) -> str:
    """グリッド線のクラス名(X通り or Y通り)を返す。"""
    if name.upper().startswith('X'):
        return CLASS_X
    elif name.upper().startswith('Y'):
        return CLASS_Y
    else:
        return CLASS_X if abs(cx1 - cx2) < abs(cy1 - cy2) else CLASS_Y


def build_grid_commands(ifc_file: ifcopenshell.file) -> list[GridCommand]:
    """IFC の通り芯から grid 命令のリストを組み立てる。

    座標はバウンディングボックス中心でセンタリングし VectorWorks 原点付近に揃える。
    """
    lines_to_draw, center_x, center_y = resolve_lines(ifc_file)

    commands: list[GridCommand] = []
    for x1, y1, x2, y2, name in lines_to_draw:
        cx1, cy1 = x1 - center_x, y1 - center_y
        cx2, cy2 = x2 - center_x, y2 - center_y
        commands.append({
            'label': name,
            'layer': TARGET_LAYER,
            'class': determine_class(name, cx1, cy1, cx2, cy2),
            'start': [cx1, cy1],
            'end': [cx2, cy2],
        })
    return commands
