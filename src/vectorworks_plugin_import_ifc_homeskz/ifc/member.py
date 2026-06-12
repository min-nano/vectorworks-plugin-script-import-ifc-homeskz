"""横架材 (IfcBeam / IfcMember) の解析と member 命令の組み立て。vs 非依存。

IFC の IfcBeam / IfcMember を走査し、各階の横架材天端レイヤ
（最上階は軒高レイヤ）に配置する member 命令を生成する。
構造材 ID は断面寸法と材種から "{幅}×{背} - {材種}" の形式で自動生成する。

横架材同士が T 字状に食い込んでいる箇所（甲乙梁の取り合い等）は、
食い込む側の端部を相手梁の面まで詰めて干渉を解消する
（``resolve_member_interferences``）。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import MemberCommand
from .grid import resolve_lines
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
    resolve_beam_top_offset,
)

if TYPE_CHECKING:
    import ifcopenshell

_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')

# 横架材同士の食い込み（T 字状の取り合い）を解消する際の許容値 (mm)
_Z_OVERLAP_TOL = 1.0    # この値以下の Z 重なりは干渉とみなさない（段差梁は対象外）
_PARALLEL_TOL = 1e-6    # 軸がほぼ平行な相手は対象外（食い込みでなく継ぎ手）
_END_TOL = 1.0          # 相手梁の端部近傍（L 字仕口）を対象外にする余裕
_MIN_TRIM = 1.0         # この値未満の食い込みは調整しない
_MIN_LENGTH = 1.0       # 調整後にこの長さ未満になる場合は調整しない


def _get_placement_2d(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float, float, float] | None:
    """IfcProduct のローカル配置から 2D 座標 (ox, oy, dx, dy) を返す。

    取得できない場合は None を返す。
    dx, dy は梁軸方向の単位ベクトル（Axis の XY 成分）。
    ホームズ君 IFC では押し出し方向が常にローカル Z (Axis) なので
    梁の延伸方向 = Axis 属性を使う。Axis が未設定の場合は (1.0, 0.0) を使う。
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
    ox, oy = float(coords[0]), float(coords[1])

    axis = rel.Axis
    if axis is not None and len(axis.DirectionRatios) >= 2:
        dx = float(axis.DirectionRatios[0])
        dy = float(axis.DirectionRatios[1])
        norm = math.hypot(dx, dy)
        if norm > 0.0:
            dx, dy = dx / norm, dy / norm
        else:
            dx, dy = 1.0, 0.0
    else:
        dx, dy = 1.0, 0.0

    return ox, oy, dx, dy


def _get_profile_dims(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float, float] | None:
    """IfcProduct の体ジオメトリから断面寸法 (width, height, length) を返す。

    Body 表現の IfcExtrudedAreaSolid + IfcRectangleProfileDef を解析する。
    見つからない場合は None を返す。
    """
    rep = getattr(element, 'Representation', None)
    if rep is None:
        return None
    for shape_rep in rep.Representations:
        if shape_rep.RepresentationIdentifier != 'Body':
            continue
        for item in shape_rep.Items:
            if not item.is_a('IfcExtrudedAreaSolid'):
                continue
            area = item.SweptArea
            if not area.is_a('IfcRectangleProfileDef'):
                continue
            return float(area.XDim), float(area.YDim), float(item.Depth)
    return None


def _get_material_name(element: ifcopenshell.entity_instance) -> str:
    """IfcProduct に関連付けられた材種名を返す。見つからない場合は空文字。"""
    for rel in getattr(element, 'HasAssociations', ()):
        if not rel.is_a('IfcRelAssociatesMaterial'):
            continue
        mat = rel.RelatingMaterial
        if mat.is_a('IfcMaterial'):
            return mat.Name or ''
        if mat.is_a('IfcMaterialList') and mat.Materials:
            return mat.Materials[0].Name or ''
        if mat.is_a('IfcMaterialLayerSetUsage'):
            layers = mat.ForLayerSet.MaterialLayers
            if layers:
                return layers[0].Material.Name or ''
    return ''


def make_member_id(width: float, height: float, material: str) -> str:
    """断面寸法と材種名から構造材 ID 文字列を生成する。

    例: make_member_id(120, 180, '杉対称異等級集成材E105-F355')
        → '120×180 - 杉対称異等級集成材E105-F355'
    """
    w = int(round(width))
    h = int(round(height))
    return f'{w}×{h} - {material}' if material else f'{w}×{h}'


def _z_overlaps(elev_a: float, height_a: float,
                elev_b: float, height_b: float) -> bool:
    """2 つの横架材の Z 範囲（[天端 - 背, 天端]）が重なるか判定する。

    elevation は横架材天端の絶対高さで、断面は天端から背だけ下方に伸びる。
    重なりが許容値以下（段差で上下に離れている等）なら干渉とみなさない。
    """
    top_a, bottom_a = elev_a, elev_a - height_a
    top_b, bottom_b = elev_b, elev_b - height_b
    return min(top_a, top_b) - max(bottom_a, bottom_b) > _Z_OVERLAP_TOL


def _trim_distance_for_end(
    px: float, py: float, gx: float, gy: float,
    others: list[tuple[float, float, float, float, float, float]],
) -> float:
    """端点 (px, py)・外向き単位ベクトル (gx, gy) の食い込み量 s (>= 0) を返す。

    others は相手梁 (sx, sy, ux, uy, length, half_width) のリスト。
    端点が相手梁の矩形「内部」（T 字状の取り合い）に食い込むとき、相手梁の
    手前の面まで端点を軸方向に引き戻すのに必要な距離を返す。複数の相手に
    食い込む場合はすべての面より外側になるよう最大値を採用する。食い込みが
    無い、もしくは相手の端部近傍（L 字仕口）・平行（継ぎ手）の場合は 0。
    """
    best = 0.0
    for sx, sy, ux, uy, length, hw in others:
        # 相手梁の断面幅方向（中心線に直交する単位ベクトル）
        pbx, pby = -uy, ux
        a = gx * pbx + gy * pby
        if abs(a) < _PARALLEL_TOL:
            continue  # ほぼ平行 → 食い込みではなく継ぎ手
        dpx, dpy = px - sx, py - sy
        d = dpx * pbx + dpy * pby      # 相手中心線からの符号付き距離
        if abs(d) > hw:
            continue                    # 端点が相手の幅内に無い（食い込んでいない）
        t = dpx * ux + dpy * uy         # 相手軸方向の位置
        if not (_END_TOL < t < length - _END_TOL):
            continue                    # 相手端部近傍（L 字）は調整しない
        # 端点が侵入してきた側（手前）の面まで引き戻す
        target = -math.copysign(hw, a)
        s = (d - target) / a
        if s > best:
            best = s
    return best if best > _MIN_TRIM else 0.0


def resolve_member_interferences(
    commands: list[MemberCommand],
) -> list[MemberCommand]:
    """横架材同士の T 字状の食い込みを解消するよう端部の長さを調整する。

    ある横架材の端点が別の横架材の矩形内部（端部近傍を除く）に食い込み、
    かつ Z 範囲・配置レイヤが一致する場合、相手梁（通し材）の手前の面まで
    端点を引き戻す。相手梁の形状は変えず、食い込む側のみ短くする。

    判定は入力時点のジオメトリ（スナップショット）に対して行うため、
    命令の並び順に依存しない決定的な結果になる。入力 commands は変更せず、
    調整後の新しいリストを返す。
    """
    geoms: list[tuple[float, float, float, float, float, float, float] | None] = []
    for c in commands:
        sx, sy = c['start']
        ex, ey = c['end']
        dx, dy = ex - sx, ey - sy
        length = math.hypot(dx, dy)
        if length <= 0.0:
            geoms.append(None)
        else:
            geoms.append((sx, sy, ex, ey, dx / length, dy / length, length))

    result: list[MemberCommand] = []
    for i, command in enumerate(commands):
        gi = geoms[i]
        new_start = list(command['start'])
        new_end = list(command['end'])
        if gi is not None:
            sx, sy, ex, ey, ux, uy, length = gi
            others: list[tuple[float, float, float, float, float, float]] = []
            for j, other in enumerate(commands):
                gj = geoms[j]
                if j == i or gj is None:
                    continue
                if command['layer'] != other['layer']:
                    continue
                if not _z_overlaps(command['elevation'], command['height'],
                                   other['elevation'], other['height']):
                    continue
                others.append((gj[0], gj[1], gj[4], gj[5], gj[6], other['width'] / 2.0))

            s_end = _trim_distance_for_end(ex, ey, ux, uy, others)
            s_start = _trim_distance_for_end(sx, sy, -ux, -uy, others)
            if length - s_start - s_end > _MIN_LENGTH:
                new_start = [sx + ux * s_start, sy + uy * s_start]
                new_end = [ex - ux * s_end, ey - uy * s_end]

        result.append({
            'layer': command['layer'],
            'member_id': command['member_id'],
            'start': new_start,
            'end': new_end,
            'width': command['width'],
            'height': command['height'],
            'elevation': command['elevation'],
        })

    return result


def build_member_commands(ifc_file: ifcopenshell.file) -> list[MemberCommand]:
    """IFC の横架材から member 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    最上階（屋根）には横架材天端レイヤが存在しないため軒高レイヤを指定する。
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
    commands: list[MemberCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 最上階は横架材天端レイヤがなく軒高レイヤに配置する
        layer_suffix = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layer_name = f'{prefix}-{layer_suffix}'

        storey_elevation = float(storey.Elevation or 0.0)
        if is_top:
            layer_elevation = storey_elevation
        else:
            layer_elevation = storey_elevation + resolve_beam_top_offset(storey)

        for rel in storey.ContainsElements:
            for element in rel.RelatedElements:
                if not any(element.is_a(t) for t in _IFC_MEMBER_TYPES):
                    continue

                placement = _get_placement_2d(element)
                if placement is None:
                    continue
                dims = _get_profile_dims(element)
                if dims is None:
                    continue

                ox, oy, dx, dy = placement
                width, height, length = dims

                x1 = ox - center_x
                y1 = oy - center_y
                x2 = x1 + dx * length
                y2 = y1 + dy * length

                # 各横架材は固定の横架材天端高さではなく、IFC 上の実際の
                # ローカル配置 Z で描画する。基準高さ（横架材天端）にない梁も
                # 正しい高さに配置するため。Z が取得できない梁のみレイヤ基準高さを使う。
                local_z = get_local_placement_z(element)
                if local_z is None:
                    elevation = layer_elevation
                else:
                    elevation = storey_elevation + local_z

                material = _get_material_name(element)
                member_id = make_member_id(width, height, material)

                commands.append({
                    'layer': layer_name,
                    'member_id': member_id,
                    'start': [x1, y1],
                    'end': [x2, y2],
                    'width': width,
                    'height': height,
                    'elevation': elevation,
                })

    # 横架材同士が食い込んでいる箇所は端部の長さを詰めて干渉を解消する
    return resolve_member_interferences(commands)
