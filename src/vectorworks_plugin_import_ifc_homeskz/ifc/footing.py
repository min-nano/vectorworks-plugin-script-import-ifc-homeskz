"""基礎(立上り・底盤・地中梁、IfcFooting/IfcSlab)の解析と命令の組み立て。vs 非依存。

ホームズ君 IFC の基礎要素を 3 種に分類して別オブジェクトに変換する。

- 立上り(基礎梁): ``Name`` が ``基礎梁`` で始まる IfcFooting。壁オブジェクト
  (wall 命令)にする。下端は基礎(自階)の GL、上端は 1 階(上階)の横架材天端に
  バインドする。
- 底盤(基礎底盤・布基礎底盤・独立基礎底盤): ``Name`` に ``底盤`` を含む
  IfcSlab/IfcFooting。スラブオブジェクト(slab 命令)にする。天端を基礎の
  底盤天端レベルにバインドする。
- 地中梁(地中梁・部分地中梁): ``Name`` に ``地中梁`` を含む IfcFooting。
  底盤の下にぶら下がるためスラブオブジェクトにし、実形状どおり底盤天端より
  低い天端にバインドする(底盤と噛み合う)。

底盤天端レベルの高さは、底盤(基礎底盤系)の天端 Z ごとに平面面積を合計し、
合計面積が最大の天端 Z を採用する(エンティティ列挙順に依存しない決定的な高さ)。

押し出しソリッド(IfcExtrudedAreaSolid)の配置・押し出し方向は要素ごとに異なる
(底盤は鉛直押し出し、立上り・地中梁・布基礎底盤は水平押し出し)ため、配置行列を
組んでワールド座標に変換し、押し出し方向が鉛直か水平かで平面外形の求め方を分ける。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from ..document import SlabCommand, StoryBoundCommand, StoryCommand, WallCommand
from .grid import resolve_lines
from .story import (
    FOUNDATION_SUFFIX,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LEVEL_BEAM_TOP,
    LEVEL_GL,
    LEVEL_SLAB_TOP,
    STORY_FOUNDATION,
    resolve_beam_top_offset,
)

if TYPE_CHECKING:
    import ifcopenshell

# 基礎要素を分類する Name 接頭辞・部分文字列
_WALL_PREFIX = '基礎梁'        # 立上り(壁)
_GROUND_BEAM_TOKEN = '地中梁'  # 地中梁・部分地中梁(スラブ・底盤の下)
_BASE_SLAB_TOKEN = '底盤'      # 基礎底盤・布基礎底盤・独立基礎底盤(底盤スラブ)

# 構造クラス(参照スクリプトのクラス階層 04構造-01基礎)
CLASS_FOUNDATION_WALL = '04構造-01基礎-03立ち上がり'
CLASS_FOUNDATION_SLAB = '04構造-01基礎-02基礎スラブ'

# 押し出し方向が鉛直とみなす Z 成分の閾値(|z| > これ)
_VERTICAL_EXTRUDE_TOL = 0.9

# 3 次元ベクトル(ワールド座標)
_Vec = tuple[float, float, float]


def _normalize(v: _Vec) -> _Vec:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 0.0 else v


def _cross(a: _Vec, b: _Vec) -> _Vec:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a: _Vec, b: _Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _add(a: _Vec, b: _Vec) -> _Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: _Vec, b: _Vec) -> _Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: _Vec, s: float) -> _Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


# 配置(原点 O と正規直交軸 lX, lY, lZ)
_Placement = tuple[_Vec, _Vec, _Vec, _Vec]


def _axis_placement(p: ifcopenshell.entity_instance) -> _Placement:
    """IfcAxis2Placement3D からワールドの (原点, lX, lY, lZ) を返す。

    Axis(=lZ)・RefDirection(=lX)からグラム・シュミットで正規直交基底を作る。
    どちらも省略可能で、既定は lZ=(0,0,1)、lX=(1,0,0)。
    """
    coords = p.Location.Coordinates
    origin: _Vec = (float(coords[0]), float(coords[1]),
                    float(coords[2]) if len(coords) > 2 else 0.0)
    lz: _Vec = (0.0, 0.0, 1.0)
    if p.Axis is not None:
        d = p.Axis.DirectionRatios
        lz = _normalize((float(d[0]), float(d[1]), float(d[2])))
    lx: _Vec = (1.0, 0.0, 0.0)
    if p.RefDirection is not None:
        d = p.RefDirection.DirectionRatios
        lx = (float(d[0]), float(d[1]), float(d[2]))
    lx = _normalize(_sub(lx, _scale(lz, _dot(lx, lz))))
    if lx == (0.0, 0.0, 0.0):
        lx = (1.0, 0.0, 0.0)
    ly = _cross(lz, lx)
    return origin, lx, ly, lz


def _compose(element: _Placement, item: _Placement) -> _Placement:
    """要素配置 element と表現アイテム配置 item を合成する。

    item 座標系の点 p は world = O_e + R_e @ (O_i + R_i @ p) に変換される。
    合成後の原点・軸を返す。
    """
    oe, ex, ey, ez = element
    oi, ix, iy, iz = item

    def apply_re(v: _Vec) -> _Vec:
        return _add(_add(_scale(ex, v[0]), _scale(ey, v[1])), _scale(ez, v[2]))

    return _add(oe, apply_re(oi)), apply_re(ix), apply_re(iy), apply_re(iz)


# 押し出しソリッドのワールド情報。
# 注: モジュールレベルの型エイリアス代入は実行時に評価されるため、PEP 604 の
# ``X | None`` ではなく ``Optional[...]`` を使う(Python 3.9 では実行時の ``|``
# 合成が未対応で mypy も無効なエイリアスとして拒否するため)。
_Solid = tuple[_Placement, _Vec, float, list[tuple[float, float]],
               Optional[tuple[float, float]]]


def _base_extruded_solid(
    item: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance | None:
    """表現アイテムから基となる IfcExtrudedAreaSolid を返す。無ければ None。

    端部が他材で削られた立上り・底盤は IfcBooleanResult(差演算)で表現される。
    その場合は第 1 オペランド(削られる前の素のソリッド)を辿る。素の形状を
    使うと削り分だけ長めになるが、要素を取り逃すよりは妥当な近似になる。
    """
    while item.is_a('IfcBooleanResult') or item.is_a('IfcBooleanClippingResult'):
        item = item.FirstOperand
    if item.is_a('IfcExtrudedAreaSolid'):
        return item
    return None


def _first_extruded_solid(
    element: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance | None:
    """要素の Body 表現から最初の IfcExtrudedAreaSolid を返す。無ければ None。"""
    rep = getattr(element, 'Representation', None)
    if rep is None:
        return None
    for shape_rep in rep.Representations:
        for item in shape_rep.Items:
            solid = _base_extruded_solid(item)
            if solid is not None:
                return solid
    return None


def _profile_points(
    area: ifcopenshell.entity_instance,
) -> tuple[list[tuple[float, float]], tuple[float, float] | None] | None:
    """断面プロファイルの 2D 頂点列と (矩形なら寸法) を返す。

    IfcRectangleProfileDef は中心原点の 4 隅(2D Position の平行移動を反映)、
    IfcArbitraryClosedProfileDef は OuterCurve の頂点列を返す。
    """
    if area.is_a('IfcRectangleProfileDef'):
        hx, hy = float(area.XDim) / 2.0, float(area.YDim) / 2.0
        pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
        pos = area.Position
        if pos is not None and pos.Location is not None:
            ox, oy = pos.Location.Coordinates
            pts = [(u + float(ox), v + float(oy)) for u, v in pts]
        return pts, (float(area.XDim), float(area.YDim))
    if area.is_a('IfcArbitraryClosedProfileDef'):
        outer = area.OuterCurve
        if not outer.is_a('IfcPolyline'):
            return None
        pts = [(float(pt.Coordinates[0]), float(pt.Coordinates[1]))
               for pt in outer.Points]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        return pts, None
    return None


def _world_solid(element: ifcopenshell.entity_instance) -> _Solid | None:
    """要素の押し出しソリッドをワールド座標の情報に変換する。

    Returns: (配置, 押し出し方向(単位ベクトル), 押し出し長, プロファイル頂点列,
    矩形寸法 or None)。取得できなければ None。
    """
    solid = _first_extruded_solid(element)
    if solid is None:
        return None
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None or placement.RelativePlacement is None:
        return None
    element_pl = _axis_placement(placement.RelativePlacement)
    pos = solid.Position
    pl = _compose(element_pl, _axis_placement(pos)) if pos is not None else element_pl

    _, lx, ly, lz = pl
    d = solid.ExtrudedDirection.DirectionRatios
    local_dir = _normalize((float(d[0]), float(d[1]), float(d[2])))
    extrude = _add(_add(_scale(lx, local_dir[0]), _scale(ly, local_dir[1])),
                   _scale(lz, local_dir[2]))
    parsed = _profile_points(solid.SweptArea)
    if parsed is None:
        return None
    pts, dims = parsed
    return pl, extrude, float(solid.Depth), pts, dims


def _z_top_and_thickness(solid: _Solid) -> tuple[float, float]:
    """ソリッドのワールド最上端 Z と Z 方向の厚みを返す。"""
    (origin, lx, ly, _lz), extrude, depth, pts, _dims = solid
    zs: list[float] = []
    for u, v in pts:
        base = _add(_add(origin, _scale(lx, u)), _scale(ly, v))
        zs.append(base[2])
        zs.append(base[2] + extrude[2] * depth)
    return max(zs), max(zs) - min(zs)


def _footprint(solid: _Solid) -> list[tuple[float, float]]:
    """ソリッドの平面外形(XY 頂点列)を返す。

    鉛直押し出し(底盤)はプロファイルがそのまま平面外形。水平押し出し
    (地中梁・布基礎底盤)はプロファイルが鉛直面内にあるため、断面の水平方向の
    幅(プロファイル第 1 座標の範囲)を押し出し方向に掃引した矩形を外形とする。
    """
    (origin, lx, ly, _lz), extrude, depth, pts, _dims = solid
    if abs(extrude[2]) > _VERTICAL_EXTRUDE_TOL:
        footprint: list[tuple[float, float]] = []
        for u, v in pts:
            p = _add(_add(origin, _scale(lx, u)), _scale(ly, v))
            footprint.append((p[0], p[1]))
        return footprint
    us = [u for u, _v in pts]
    umin, umax = min(us), max(us)

    def corner(u: float, t: float) -> tuple[float, float]:
        p = _add(_add(origin, _scale(lx, u)), _scale(extrude, depth * t))
        return (p[0], p[1])

    return [corner(umin, 0.0), corner(umax, 0.0),
            corner(umax, 1.0), corner(umin, 1.0)]


def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    """多角形の面積(絶対値)を返す。"""
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _is_wall(name: str) -> bool:
    return name.startswith(_WALL_PREFIX)


def _is_ground_beam(name: str) -> bool:
    return _GROUND_BEAM_TOKEN in name


def _is_base_slab(name: str) -> bool:
    return _BASE_SLAB_TOKEN in name


def _iter_footing_elements(
    ifc_file: ifcopenshell.file,
) -> list[ifcopenshell.entity_instance]:
    """基礎の対象要素(IfcFooting と基礎底盤の IfcSlab)を返す。"""
    elements = list(ifc_file.by_type('IfcFooting'))
    elements += [s for s in ifc_file.by_type('IfcSlab')
                 if _is_base_slab(s.Name or '')]
    return elements


def resolve_slab_top_elevation(ifc_file: ifcopenshell.file) -> float | None:
    """底盤天端の絶対 Z を返す。底盤が無ければ None。

    底盤(基礎底盤系)の天端 Z ごとに平面面積を合計し、合計面積が最大の天端 Z を
    採用する(列挙順に依存しない決定的な高さ)。同一面積の場合は高い方を採る。
    """
    areas: dict[float, float] = {}
    for element in _iter_footing_elements(ifc_file):
        name = element.Name or ''
        if not _is_base_slab(name):
            continue
        solid = _world_solid(element)
        if solid is None:
            continue
        top, _thickness = _z_top_and_thickness(solid)
        key = round(top, 3)
        areas[key] = areas.get(key, 0.0) + _shoelace_area(_footprint(solid))
    if not areas:
        return None
    best_top = max(areas, key=lambda z: (areas[z], z))
    return best_top


def has_foundation(ifc_file: ifcopenshell.file) -> bool:
    """基礎(立上り・底盤・地中梁)が 1 つでもあれば True。"""
    for element in _iter_footing_elements(ifc_file):
        name = element.Name or ''
        if _is_wall(name) or _is_ground_beam(name) or _is_base_slab(name):
            return True
    return False


def build_foundation_story_command(
    ifc_file: ifcopenshell.file,
) -> StoryCommand | None:
    """基礎ストーリの story 命令を返す。基礎要素が無ければ None。

    ストーリ高さは GL=0。レベルは GL(0、F-立上りレイヤ)と底盤天端(底盤天端の
    絶対 Z、F-底盤レイヤ)。``levels`` の並びは希望スタック順(上→下)で、
    立上り(GL)を底盤(底盤天端)の上に積むため GL を先頭にする。
    """
    if not has_foundation(ifc_file):
        return None
    slab_top = resolve_slab_top_elevation(ifc_file)
    slab_top_offset = slab_top if slab_top is not None else 0.0
    return {
        'name': STORY_FOUNDATION,
        'suffix': FOUNDATION_SUFFIX,
        'elevation': 0.0,
        'levels': [
            {'type': LEVEL_GL, 'offset': 0.0, 'layer': LAYER_FOUNDATION_WALL},
            {'type': LEVEL_SLAB_TOP, 'offset': slab_top_offset,
             'layer': LAYER_FOUNDATION_SLAB},
        ],
    }


def _first_fl_storey(
    ifc_file: ifcopenshell.file,
) -> ifcopenshell.entity_instance | None:
    """最下階(1 階)の IfcBuildingStorey を返す。無ければ None。"""
    storeys = [s for s in ifc_file.by_type('IfcBuildingStorey')
               if (s.Name or '').upper().endswith('FL')]
    if not storeys:
        return None
    return min(storeys, key=lambda s: float(s.Elevation or 0.0))


def build_wall_commands(ifc_file: ifcopenshell.file) -> list[WallCommand]:
    """基礎の立上り(基礎梁)から wall 命令のリストを組み立てる。

    壁芯は配置原点からプロファイル中心線(押し出し方向)に沿った線。壁厚は矩形断面
    の幅(XDim)、上下端は実形状の絶対 Z。下端は基礎の GL、上端は 1 階の横架材天端に
    バインドし、offset はそれぞれの実 Z とバインド先レベルの絶対 Z の差。
    """
    storey = _first_fl_storey(ifc_file)
    if storey is None:
        return []
    beam_top_abs = float(storey.Elevation or 0.0) + resolve_beam_top_offset(storey)

    _, center_x, center_y = resolve_lines(ifc_file)

    commands: list[WallCommand] = []
    for element in ifc_file.by_type('IfcFooting'):
        name = element.Name or ''
        if not _is_wall(name):
            continue
        solid = _world_solid(element)
        if solid is None:
            continue
        (origin, _lx, _ly, _lz), extrude, depth, _pts, dims = solid
        # 立上りは矩形断面(幅=壁厚、背=壁高)を前提とする。非矩形断面は対象外。
        if dims is None:
            continue
        thickness, height = dims

        x1 = origin[0] - center_x
        y1 = origin[1] - center_y
        x2 = x1 + extrude[0] * depth
        y2 = y1 + extrude[1] * depth

        top_abs, _thickness = _z_top_and_thickness(solid)
        bottom_abs = top_abs - height

        bottom_bound: StoryBoundCommand = {
            'story_offset': 0, 'level': LEVEL_GL, 'offset': bottom_abs}
        top_bound: StoryBoundCommand = {
            'story_offset': 1, 'level': LEVEL_BEAM_TOP,
            'offset': top_abs - beam_top_abs}

        commands.append({
            'layer': LAYER_FOUNDATION_WALL,
            'class': CLASS_FOUNDATION_WALL,
            'start': [x1, y1],
            'end': [x2, y2],
            'thickness': thickness,
            'bottom_bound': bottom_bound,
            'top_bound': top_bound,
        })
    return commands


def build_slab_commands(ifc_file: ifcopenshell.file) -> list[SlabCommand]:
    """基礎の底盤・地中梁から slab 命令のリストを組み立てる。

    平面外形を底盤天端レベルにセンタリングして格納し、天端を底盤天端レベルに
    バインドする(offset は実天端 Z と底盤天端の絶対 Z の差)。スラブ厚は実形状の
    Z 方向の厚み。地中梁は底盤の下にぶら下がるため offset が負値になる。
    """
    slab_top = resolve_slab_top_elevation(ifc_file)
    slab_top_abs = slab_top if slab_top is not None else 0.0

    _, center_x, center_y = resolve_lines(ifc_file)

    commands: list[SlabCommand] = []
    for element in _iter_footing_elements(ifc_file):
        name = element.Name or ''
        if not (_is_ground_beam(name) or _is_base_slab(name)):
            continue
        solid = _world_solid(element)
        if solid is None:
            continue
        top_abs, thickness = _z_top_and_thickness(solid)
        boundary = [[x - center_x, y - center_y] for x, y in _footprint(solid)]
        bound: StoryBoundCommand = {
            'story_offset': 0, 'level': LEVEL_SLAB_TOP,
            'offset': top_abs - slab_top_abs}
        commands.append({
            'layer': LAYER_FOUNDATION_SLAB,
            'class': CLASS_FOUNDATION_SLAB,
            'boundary': boundary,
            'thickness': thickness,
            'bound': bound,
        })
    return commands
