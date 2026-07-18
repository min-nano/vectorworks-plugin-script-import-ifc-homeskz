"""登り梁(傾斜梁)の位置補正。vs 非依存。

ホームズ君 IFC の登り梁は位置が正確でないため、``build_member_commands`` が
組み立てた member 命令(``_sloped_member_geometry`` から拾った任意断面=平行四辺形の
側面を厚み方向へ押し出した材)を後処理で 2 点補正する。

1. **端部の食い込み解消(``_trim_noboribari_ends``)**: 登り梁の端部(直切り=鉛直面)は
   受ける材(横架材・母屋)や柱の footprint に数 mm 食い込んで入力されている。端点を
   梁軸に沿って内側へ引き戻し、鉛直な端面を受ける材/柱の手前の面に合わせる
   (``member._penetration_depth`` を再利用。柱は軸平行の断面矩形からの脱出距離で判定)。
2. **屋根勾配へのスナップ(``_snap_noboribari_to_roof``)**: ホームズ君の登り梁は軸の勾配が
   屋根版(垂木下面)より急で、天端が中央付近で屋根面と交わり両端で上下にずれる
   (始端が少し低く終端が少し高い、またはその逆)。登り梁の天端中央線の両端を、その真上に
   ある屋根版(``rafter._roof_plane``)の平面へスナップし、勾配・高さを屋根面=垂木下面に
   一致させる。屋根面が見つからない登り梁は member.py の直切りの幾何(天端=鉛直端面の
   上端)のまま残す(後方互換)。

この補正は屋根版(``rafter``)と柱(``column``)を参照するため member.py には持ち込まず、
``build_document`` が横架材命令・柱命令を組み立てた後に後処理として適用する
(垂木・野地板が屋根版から導出されるのと同じく、登り梁も屋根面を基準に整える)。
入力 members の並び順・件数は変えず(タグの member_index が保たれる)、登り梁命令だけを
更新した新しいリストを返す。判定は命令の並び順に依存しない決定的な結果になる。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import ColumnCommand, MemberCommand, StoryBoundCommand
from .grid import resolve_lines
from .member import _penetration_depth
from .rafter import _roof_plane
from .structural_class import CLASS_NOBORIBARI

if TYPE_CHECKING:
    import ifcopenshell

_Vec3 = tuple[float, float, float]

# 端部の食い込み解消・屋根スナップの許容値 (mm)
_Z_OVERLAP_TOL = 1.0    # 受ける材/柱との Z 重なりがこの値以下なら取り合いとみなさない
_MIN_TRIM = 0.5         # この値未満の食い込みは詰めない
_MIN_LENGTH = 1.0       # 詰めた後にこの長さ未満になる端は詰めない
# 屋根面の法線水平成分と登り梁の勾配方向の内積(単位)の下限。屋根面の勾配方向が
# 登り梁の勾配方向と平行(この値以上)な屋根版だけをその登り梁の屋根面とみなす。
_SLOPE_DIR_DOT = 0.9
_FLAT_TOL = 1e-6        # 法線水平成分がこれ以下(ほぼ水平)な屋根版は勾配方向が定まらない


class _RoofPlane:
    """屋根版 1 面の平面情報(ワールド座標)。登り梁の天端スナップに使う。

    ``normal`` は上向き単位法線、``anchor`` は平面上の 1 点(ワールド XY・ストーリ相対 Z)、
    ``storey_elevation`` はストーリ Elevation(絶対 Z へ足す)、``footprint`` は平面外形の
    ワールド XY 頂点列。座標は ``rafter._roof_plane`` と同じ規約(XY 絶対・Z ストーリ相対)。
    """

    def __init__(self, normal: _Vec3, anchor: _Vec3,
                 storey_elevation: float, footprint: list[tuple[float, float]]) -> None:
        self.normal = normal
        self.anchor = anchor
        self.storey_elevation = storey_elevation
        self.footprint = footprint

    def z_at(self, wx: float, wy: float) -> float:
        """平面上のワールド点 (wx, wy) の絶対 Z を返す。"""
        nx, ny, nz = self.normal
        ax, ay, az = self.anchor
        return az - (nx * (wx - ax) + ny * (wy - ay)) / nz + self.storey_elevation

    def contains(self, wx: float, wy: float) -> bool:
        """ワールド XY (wx, wy) が平面外形内(内包)なら True(走査線法)。"""
        inside = False
        n = len(self.footprint)
        j = n - 1
        for i in range(n):
            xi, yi = self.footprint[i]
            xj, yj = self.footprint[j]
            if (yi > wy) != (yj > wy) and \
                    wx < (xj - xi) * (wy - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside


def _collect_roof_planes(ifc_file: ifcopenshell.file) -> list[_RoofPlane]:
    """FL ストーリの屋根版(``屋根版`` 始まりの IfcSlab)から屋根面を集める。

    ``rafter._roof_plane`` でワールド外形頂点列と単位法線を得て、ストーリ Elevation と
    ともに ``_RoofPlane`` にする。座標は XY 絶対・Z ストーリ相対(z_at で絶対 Z にする)。
    """
    planes: list[_RoofPlane] = []
    for storey in ifc_file.by_type('IfcBuildingStorey'):
        if not (storey.Name or '').upper().endswith('FL'):
            continue
        elevation = float(storey.Elevation or 0.0)
        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not element.is_a('IfcSlab'):
                    continue
                if not (element.Name or '').startswith('屋根版'):
                    continue
                plane = _roof_plane(element)
                if plane is None:
                    continue
                verts, normal = plane
                if math.hypot(normal[0], normal[1]) <= _FLAT_TOL:
                    continue  # ほぼ水平な屋根版は勾配方向が定まらない
                footprint = [(v[0], v[1]) for v in verts]
                planes.append(_RoofPlane(normal, verts[0], elevation, footprint))
    return planes


def _roof_plane_for(
    command: MemberCommand, planes: list[_RoofPlane],
    center_x: float, center_y: float,
) -> _RoofPlane | None:
    """登り梁の真上にある屋根面を返す(勾配方向が平行・外形が中点/端点を内包)。

    登り梁の勾配方向(始端→終端の水平単位ベクトル)と屋根面の法線水平成分が平行
    (``_SLOPE_DIR_DOT`` 以上)で、外形が登り梁の中点(取れなければ端点)を内包する屋根面。
    命令座標はグリッド中心オフセット済みなので ``+center`` でワールドに戻して判定する。
    """
    sx, sy = command['start']
    ex, ey = command['end']
    dx, dy = ex - sx, ey - sy
    d = math.hypot(dx, dy)
    if d < _MIN_LENGTH:
        return None
    sdx, sdy = dx / d, dy / d
    probes = [
        ((sx + ex) / 2.0 + center_x, (sy + ey) / 2.0 + center_y),
        (sx + center_x, sy + center_y),
        (ex + center_x, ey + center_y),
    ]
    for plane in planes:
        nx, ny, _nz = plane.normal
        dh = math.hypot(nx, ny)
        if dh <= _FLAT_TOL:
            continue
        if abs((nx * sdx + ny * sdy) / dh) < _SLOPE_DIR_DOT:
            continue
        if any(plane.contains(wx, wy) for wx, wy in probes):
            return plane
    return None


def _column_penetration(
    px: float, py: float, gx: float, gy: float, column: ColumnCommand,
) -> float:
    """端点 (px, py)・外向き (gx, gy) が柱の断面矩形(軸平行)に食い込む量を返す。

    端点が柱の矩形内部にあるとき、内側方向 (-g) へ引き戻して柱の手前の面まで出すのに
    必要な距離(>= 0)を返す。食い込んでいなければ 0。柱は方向を持たないため軸平行矩形で扱う。
    """
    cx, cy = column['position']
    hwx = column['width'] / 2.0
    hwy = column['depth'] / 2.0
    if abs(px - cx) > hwx or abs(py - cy) > hwy:
        return 0.0
    dinx, diny = -gx, -gy  # 内側方向
    dists: list[float] = []
    if abs(dinx) > 1e-9:
        face = cx + hwx if dinx > 0 else cx - hwx
        dists.append((face - px) / dinx)
    if abs(diny) > 1e-9:
        face = cy + hwy if diny > 0 else cy - hwy
        dists.append((face - py) / diny)
    dists = [t for t in dists if t > 0.0]
    return min(dists) if dists else 0.0


def _end_trim(
    px: float, py: float, gx: float, gy: float,
    z_bottom: float, z_top: float,
    receivers: list[MemberCommand], columns: list[ColumnCommand],
) -> float:
    """登り梁の端点 (px, py)・外向き (gx, gy) を受ける材/柱の面まで詰める量を返す。

    Z 範囲が重なる受ける材(横架材・母屋)・柱の footprint に食い込む量の最大値。
    平行な材(継ぎ手・側並び)は ``_penetration_depth`` が 0 を返すため対象外。
    """
    best = 0.0
    for m in receivers:
        sx, sy = m['start']
        ex, ey = m['end']
        d = math.hypot(ex - sx, ey - sy)
        if d < _MIN_LENGTH:
            continue
        m_top = max(m['elevation'], m['end_elevation'])
        m_bottom = min(m['elevation'], m['end_elevation']) - m['height']
        if min(z_top, m_top) - max(z_bottom, m_bottom) <= _Z_OVERLAP_TOL:
            continue
        s = _penetration_depth(
            px, py, gx, gy, sx, sy, (ex - sx) / d, (ey - sy) / d, d, m['width'] / 2.0)
        best = max(best, s)
    for c in columns:
        c_top = c['elevation'] + c['height']
        if min(z_top, c_top) - max(z_bottom, c['elevation']) <= _Z_OVERLAP_TOL:
            continue
        best = max(best, _column_penetration(px, py, gx, gy, c))
    return best


def correct_noboribari(
    ifc_file: ifcopenshell.file,
    members: list[MemberCommand],
    columns: list[ColumnCommand],
) -> list[MemberCommand]:
    """登り梁の端部食い込みを解消し、天端を屋根面(垂木下面)へスナップする。

    ``members`` のうち登り梁(``CLASS_NOBORIBARI``)命令だけを補正し、他は素通しする。
    件数・並び順は保つ(タグの ``member_index`` を保つため)。屋根面が見つからない登り梁は
    天端スナップをせず、端部の食い込み解消だけ行う。判定は命令の並び順に依存しない。
    """
    _, center_x, center_y = resolve_lines(ifc_file)
    planes = _collect_roof_planes(ifc_file)
    receivers = [m for m in members if m['class'] != CLASS_NOBORIBARI]

    result: list[MemberCommand] = []
    for command in members:
        if command['class'] != CLASS_NOBORIBARI:
            result.append(command)
            continue
        result.append(_correct_one(command, planes, receivers, columns,
                                   center_x, center_y))
    return result


def _correct_one(
    command: MemberCommand, planes: list[_RoofPlane],
    receivers: list[MemberCommand], columns: list[ColumnCommand],
    center_x: float, center_y: float,
) -> MemberCommand:
    """登り梁命令 1 件を補正する(端部食い込み解消 → 屋根面スナップ)。"""
    sx, sy = command['start']
    ex, ey = command['end']
    d = math.hypot(ex - sx, ey - sy)
    if d < _MIN_LENGTH:
        return command
    ux, uy = (ex - sx) / d, (ey - sy) / d

    z_top = max(command['elevation'], command['end_elevation'])
    z_bottom = min(command['elevation'], command['end_elevation']) - command['height']

    # 1. 端部の食い込み解消: 始端は外向き -u、終端は外向き +u。詰めた後に極小長に
    #    ならない範囲で端点を軸に沿って内側へ引き戻す。
    s_start = _end_trim(sx, sy, -ux, -uy, z_bottom, z_top, receivers, columns)
    s_end = _end_trim(ex, ey, ux, uy, z_bottom, z_top, receivers, columns)
    if s_start < _MIN_TRIM:
        s_start = 0.0
    if s_end < _MIN_TRIM:
        s_end = 0.0
    if d - s_start - s_end < _MIN_LENGTH:
        s_start = s_end = 0.0
    nsx, nsy = sx + ux * s_start, sy + uy * s_start
    nex, ney = ex - ux * s_end, ey - uy * s_end

    elevation = command['elevation']
    end_elevation = command['end_elevation']
    start_bound = command['start_bound']
    end_bound = command['end_bound']

    # 2. 屋根面スナップ: 天端中央線の両端(詰めた後の XY)を屋根面へ落として勾配・高さを
    #    垂木下面に合わせる。屋根面が無ければ member.py の直切りの幾何のまま残す。
    plane = _roof_plane_for(command, planes, center_x, center_y)
    if plane is not None:
        # レベルの絶対 Z(バインド先=登り梁レベル)。offset を差し引いて逆算する。
        level_z = elevation - start_bound['offset']
        elevation = plane.z_at(nsx + center_x, nsy + center_y)
        end_elevation = plane.z_at(nex + center_x, ney + center_y)
        new_start_bound: StoryBoundCommand = {
            'story_offset': start_bound['story_offset'],
            'level': start_bound['level'],
            'offset': elevation - level_z}
        new_end_bound: StoryBoundCommand = {
            'story_offset': end_bound['story_offset'],
            'level': end_bound['level'],
            'offset': end_elevation - level_z}
        start_bound = new_start_bound
        end_bound = new_end_bound

    updated: MemberCommand = {
        'layer': command['layer'],
        'member_id': command['member_id'],
        'class': command['class'],
        'start': [nsx, nsy],
        'end': [nex, ney],
        'width': command['width'],
        'height': command['height'],
        'elevation': elevation,
        'end_elevation': end_elevation,
        'start_bound': start_bound,
        'end_bound': end_bound,
    }
    return updated
