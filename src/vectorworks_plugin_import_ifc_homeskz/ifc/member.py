"""横架材 (IfcBeam / IfcMember) の解析と member 命令の組み立て。vs 非依存。

IFC の IfcBeam / IfcMember を走査し、各階の横架材天端レイヤ
（最上階は軒高レイヤ）に配置する member 命令を生成する。
構造材 ID は断面寸法と材種から "{幅}×{背} - {材種}" の形式で自動生成する。

横架材同士が食い込んでいる箇所（甲乙梁の T 字や出隅の L 字の取り合い等）は、
相互の食い込み量を比べて勝ち負けを判定し、負け側（深く食い込む側）の端部を
相手梁の面まで詰めて干渉を解消する（``resolve_member_interferences``）。
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

# 横架材同士の食い込み（T 字・L 字の取り合い）を解消する際の許容値 (mm)
_Z_OVERLAP_TOL = 1.0    # この値以下の Z 重なりは干渉とみなさない（段差梁は対象外）
_PARALLEL_TOL = 1e-6    # 軸がほぼ平行な相手は対象外（食い込みでなく継ぎ手）
_ALONG_TOL = 1.0        # 相手梁の軸方向の範囲判定の余裕（角部も含めるため端まで許容）
_FACE_TOL = 1.0         # 相手の面ちょうどで止まる材を食い込みとみなさない余裕
_MIN_TRIM = 1.0         # この値未満の食い込みは調整しない
_MIN_LENGTH = 1.0       # 調整後にこの長さ未満になる場合は調整しない
_SYMMETRY_TOL = 1.0     # 相互の食い込み量がこの差以内なら対称とみなし詰めない


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


# 梁ジオメトリ: (start_x, start_y, end_x, end_y, axis_x, axis_y, length)
_Geom = tuple[float, float, float, float, float, float, float]


def _penetration_depth(
    px: float, py: float, gx: float, gy: float,
    sx: float, sy: float, ux: float, uy: float, length: float, hw: float,
) -> float:
    """端点 (px, py)・外向き単位ベクトル (gx, gy) が相手梁の矩形に食い込む量を返す。

    相手梁は中心 (sx, sy)・軸 (ux, uy)・長さ length・半幅 hw で表す。端点が
    相手の矩形内部にあるとき、端点を軸方向 (-g) に引き戻して相手の手前の面
    まで出すのに必要な距離 (>= 0) を返す。食い込んでいない・平行な場合は 0。

    T 字（相手の途中に突き当たる）・L 字（相手の端部で突き当たる）を区別せず、
    軸方向の位置 t は相手の端まで許容する。勝ち負けの判定は呼び出し側が
    相互の食い込み量を比較して行う。
    """
    pbx, pby = -uy, ux              # 相手梁の断面幅方向（中心線に直交する単位ベクトル）
    a = gx * pbx + gy * pby
    if abs(a) < _PARALLEL_TOL:
        return 0.0                  # ほぼ平行 → 食い込みではなく継ぎ手
    dpx, dpy = px - sx, py - sy
    d = dpx * pbx + dpy * pby       # 相手中心線からの符号付き距離
    if abs(d) > hw + _FACE_TOL:
        return 0.0                  # 端点が相手の幅の外（食い込んでいない）
    t = dpx * ux + dpy * uy         # 相手軸方向の位置
    if not (-_ALONG_TOL < t < length + _ALONG_TOL):
        return 0.0                  # 相手の長さの範囲外
    # 端点が侵入してきた側（手前）の面まで引き戻す距離
    target = -math.copysign(hw, a)
    s = (d - target) / a
    return s if s > 0.0 else 0.0


def _trim_for_end(
    px: float, py: float, gx: float, gy: float,
    self_geom: _Geom, self_hw: float,
    others: list[tuple[_Geom, float]],
) -> float:
    """端点 (px, py)・外向き (gx, gy) を相手梁の面まで詰める量 s (>= 0) を返す。

    端点が相手梁 B に食い込む量 sAB が、相手 B の端部が自分 A に食い込む量
    sBA より大きい（= B の方が「通し材」側で勝ち）場合のみ詰める。相互の
    食い込み量が同等（対称な角・火打等）なら触らない。複数の相手に食い込む
    場合は、すべての面より外側になるよう最大値を採用する。
    """
    asx, asy, _aex, _aey, aux, auy, _alen = self_geom
    best = 0.0
    for (bsx, bsy, bex, bey, bux, buy, blen), b_hw in others:
        s_ab = _penetration_depth(px, py, gx, gy, bsx, bsy, bux, buy, blen, b_hw)
        if s_ab <= _MIN_TRIM:
            continue
        # 相手 B の 2 端点が自分 A に食い込む量（B 始端の外向きは -軸、終端は +軸）
        s_ba = max(
            _penetration_depth(bsx, bsy, -bux, -buy, asx, asy, aux, auy, _alen, self_hw),
            _penetration_depth(bex, bey, bux, buy, asx, asy, aux, auy, _alen, self_hw),
        )
        # 自分の方が深く食い込む（相手が勝ち）ときだけ詰める。対称なら触らない。
        if s_ab > s_ba + _SYMMETRY_TOL and s_ab > best:
            best = s_ab
    return best


def resolve_member_interferences(
    commands: list[MemberCommand],
) -> list[MemberCommand]:
    """横架材同士の食い込み（T 字・L 字の取り合い）を解消するよう端部を詰める。

    ある横架材の端点が別の横架材の矩形に食い込み、かつ Z 範囲・配置レイヤが
    一致する場合、相手梁の手前の面まで端点を引き戻す。ただし相互の食い込み量
    を比べ、自分の方が深く食い込む（相手が「通し材」で勝ち）ときだけ詰める。
    相互の食い込み量が同等な対称の角（火打等）は勝ち負けが付かないため触らない。
    相手梁の形状は変えず、食い込む側のみ短くする。

    判定は入力時点のジオメトリ（スナップショット）に対して行うため、
    命令の並び順に依存しない決定的な結果になる。入力 commands は変更せず、
    調整後の新しいリストを返す。
    """
    geoms: list[_Geom | None] = []
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
            self_hw = command['width'] / 2.0
            others: list[tuple[_Geom, float]] = []
            for j, other in enumerate(commands):
                gj = geoms[j]
                if j == i or gj is None:
                    continue
                if command['layer'] != other['layer']:
                    continue
                if not _z_overlaps(command['elevation'], command['height'],
                                   other['elevation'], other['height']):
                    continue
                others.append((gj, other['width'] / 2.0))

            s_end = _trim_for_end(ex, ey, ux, uy, gi, self_hw, others)
            s_start = _trim_for_end(sx, sy, -ux, -uy, gi, self_hw, others)
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
