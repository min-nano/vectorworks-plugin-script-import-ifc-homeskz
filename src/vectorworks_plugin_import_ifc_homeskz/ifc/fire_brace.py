"""火打(火打梁)の解析と fire_brace 命令の組み立て。vs 非依存。

ホームズ君 IFC では火打(火打梁)は ``Name`` が ``火打:…`` の IfcBeam / IfcMember
として表現される。押し出し方向が鉛直(Axis=(0,0,1))で断面が
IfcArbitraryClosedProfileDef(平面外形が火打の footprint)のため、横架材
(IfcBeam/IfcMember を矩形断面の押し出しとして扱う ``ifc/member.py``)では
拾われず(鉛直軸・非矩形断面のためスキップされる)、専用にここで処理する。

火打はコーナーで直交する 2 本の横架材の間に斜めに架かる部材で、両端の面が
それぞれの梁の側面に取り付く。要件により、火打を **ハイブリッドシンボル**
``鋼製火打`` に置換し、火打が属する階の横架材レイヤ(横架材天端、最上階は軒高)に
配置する。

**シンボルの基準点**は「横架材接合部の内側面交点」= 火打が梁に取り付く 2 面が
幾何学的に交わる内角の点。火打の平面外形(footprint)は 2 本の長辺(材の長さ方向に
平行)と 2 つの端面(各梁に取り付く面)からなる。2 つの端面の直線を延長した交点が
内角の点になる(``_base_point``)。

**回転角**は火打の向きに合わせ、基準点(内角)から火打本体の重心へ向かう方向
(内角の二等分方向)を採る(``_angle``)。シンボルの基準姿勢(0 度での向き)は
VectorWorks 上で最終確認する(描画フェーズは他要素と同じく VW 上で検証する方針)。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import FireBraceCommand
from .footing import _world_solid
from .grid import resolve_lines
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    layer_prefix_for,
)

if TYPE_CHECKING:
    import ifcopenshell

_FIRE_BRACE_TYPES = ('IfcBeam', 'IfcMember')
# 火打を識別する Name 接頭辞(火打:0_1・火打:1_2 等)
_FIRE_BRACE_PREFIX = '火打'

# 置換するハイブリッドシンボル名
SYMBOL_FIRE_BRACE = '鋼製火打'

# 鋼製火打シンボルの基準姿勢(0 度での向き)の補正。内角の二等分方向に対して
# シンボルの角度基準がずれているため、基準点周りに反時計方向へ 45 度回転させる。
_SYMBOL_ANGLE_OFFSET = 45.0

# 2 直線が平行(交点なし)とみなす行列式の閾値
_PARALLEL_TOL = 1e-9

# 2D 点
_Point = tuple[float, float]
# 2D 線分(端点ペア)
_Segment = tuple[_Point, _Point]


def _is_fire_brace(element: ifcopenshell.entity_instance) -> bool:
    """要素が火打(``Name`` が ``火打`` 始まりの IfcBeam/IfcMember)なら True。"""
    if not any(element.is_a(t) for t in _FIRE_BRACE_TYPES):
        return False
    return (element.Name or '').startswith(_FIRE_BRACE_PREFIX)


def _world_footprint(
    element: ifcopenshell.entity_instance,
) -> tuple[list[_Point], list[_Point]] | None:
    """火打の平面外形を (ワールド XY 頂点列, プロファイル局所頂点列) で返す。

    プロファイル局所頂点はワールド頂点と同じ並びで、端面(局所 Y の符号が
    始終点で反転する辺)の識別に使う。取得できなければ None。
    """
    solid = _world_solid(element)
    if solid is None:
        return None
    (origin, lx, ly, _lz), _extrude, _depth, pts, _dims = solid
    world = [
        (origin[0] + u * lx[0] + v * ly[0], origin[1] + u * lx[1] + v * ly[1])
        for u, v in pts
    ]
    return world, pts


def _segment_intersection(a: _Segment, b: _Segment) -> _Point | None:
    """2 線分を無限直線として延長した交点を返す。平行なら None。"""
    (a1, a2), (b1, b2) = a, b
    d1 = (a2[0] - a1[0], a2[1] - a1[1])
    d2 = (b2[0] - b1[0], b2[1] - b1[1])
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < _PARALLEL_TOL:
        return None
    t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / denom
    return (a1[0] + t * d1[0], a1[1] + t * d1[1])


def _end_faces(world: list[_Point], local: list[_Point]) -> list[_Segment]:
    """火打 footprint の 2 つの端面(梁に取り付く面)のワールド線分を返す。

    火打の平面外形は中心線(局所 Y=0)に対称で、2 本の長辺は局所 Y が一定
    (±半幅)、2 つの端面は局所 Y が始終点で符号反転する(中心線をまたぐ)辺。
    端面はちょうど 2 つのはずで、それ以外の場合は空リストを返す。
    """
    n = len(local)
    faces: list[_Segment] = []
    for i in range(n):
        va, vb = local[i][1], local[(i + 1) % n][1]
        if va * vb < 0.0:
            faces.append((world[i], world[(i + 1) % n]))
    return faces


def _base_point(faces: list[_Segment]) -> _Point | None:
    """2 つの端面の直線を延長した交点(内角の点)を返す。求まらなければ None。"""
    if len(faces) != 2:
        return None
    return _segment_intersection(faces[0], faces[1])


def _angle(base: _Point, world: list[_Point]) -> float:
    """火打の向きに合わせた回転角(度)を返す。

    基準点(内角)から火打本体の重心へ向かう方向(内角の二等分方向)に、シンボルの
    基準姿勢のずれを補正する ``_SYMBOL_ANGLE_OFFSET``(反時計方向 45 度)を加える。
    """
    n = len(world)
    cx = sum(p[0] for p in world) / n
    cy = sum(p[1] for p in world) / n
    bisector = math.degrees(math.atan2(cy - base[1], cx - base[0]))
    return bisector + _SYMBOL_ANGLE_OFFSET


def build_fire_brace_commands(
    ifc_file: ifcopenshell.file,
) -> list[FireBraceCommand]:
    """IFC の火打から fire_brace 命令のリストを組み立てる。

    火打は属する階の横架材レイヤ(一般階 ``n-横架材天端``、最上階 ``n-軒高``)に
    配置する(横架材と同じレイヤ)。基準点は横架材接合部の内側面交点、回転角は
    火打の向き。配置座標は通り芯・横架材と同じグリッド中心オフセットで補正する。
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
    commands: list[FireBraceCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 火打は横架材と同じレイヤ(最上階は横架材天端がなく軒高)に配置する
        layer_suffix = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
        layer_name = f'{prefix}-{layer_suffix}'

        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not _is_fire_brace(element):
                    continue
                footprint = _world_footprint(element)
                if footprint is None:
                    continue
                world, local = footprint
                base = _base_point(_end_faces(world, local))
                if base is None:
                    continue
                commands.append({
                    'layer': layer_name,
                    'symbol': SYMBOL_FIRE_BRACE,
                    'position': [base[0] - center_x, base[1] - center_y],
                    'angle': _angle(base, world),
                })

    return commands
