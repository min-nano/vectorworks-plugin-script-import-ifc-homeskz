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

from ..document import (
    SlabCommand,
    StoryBoundCommand,
    StoryCommand,
    WallCommand,
    WallJoinCommand,
)
from .grid import resolve_lines
from .story import (
    FOUNDATION_SUFFIX,
    LAYER_FOUNDATION_ANCHOR,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LEVEL_BEAM_TOP,
    LEVEL_FOUNDATION_TOP,
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

# 立上り(壁)のマージ許容値(mm)。同一直線判定の直交距離・接続判定の隙間、
# および断面キーの丸め桁に使う。単位系は mm。
_WALL_MERGE_DIST_TOL = 1.0
# 平行判定に使う単位方向ベクトルの外積(sin 角)の許容値。
_WALL_MERGE_ANGLE_TOL = 1e-3

# 壁結合(JoinWalls)の joinModifier 値。1=T 結合・2=L 結合・3=X 結合。
_JOIN_T = 1
_JOIN_L = 2
_JOIN_X = 3
# 交点が壁芯の端点とみなせる、端からの距離の許容値 (mm)。実際の端点許容は
# これに相手壁の半壁厚を足した値(_wall_intersection 参照。立上りは相手壁の
# 外面まで伸びるためコーナーの交点が端から半壁厚離れる)。
_JOIN_ENDPOINT_TOL = 1.0
# 複数の立上りが集まる交点を同一ジャンクションとみなすクラスタリング許容値 (mm)。
# 同一点に集まる立上りは壁芯どうしの交点が数学的に一致するため小さくてよい。
_JOIN_CLUSTER_TOL = 1.0
# 天端高さ(top_bound.offset)が同一とみなせる許容値 (mm)。これを超える差の壁は
# 「天端高さの異なる壁」として capped で結合する(低い壁を高い壁に結合する)。
_WALL_HEIGHT_TOL = _WALL_MERGE_DIST_TOL

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


def resolve_foundation_top_elevation(ifc_file: ifcopenshell.file) -> float | None:
    """基礎天端(立上り天端)の絶対 Z を返す。立上りが無ければ None。

    アンカーボルトの高さ基準に使う。立上り(基礎梁)の天端 Z のうち最大値を採る
    (列挙順に依存しない決定的な高さ)。立上りが 1 つも無い基礎(底盤のみ)は
    None を返し、呼び出し側が底盤天端等にフォールバックする。
    """
    tops: list[float] = []
    for element in ifc_file.by_type('IfcFooting'):
        if not _is_wall(element.Name or ''):
            continue
        solid = _world_solid(element)
        if solid is None:
            continue
        top, _thickness = _z_top_and_thickness(solid)
        tops.append(top)
    return max(tops) if tops else None


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

    ストーリ高さは GL=0。レベルは基礎天端(立上り天端の絶対 Z、F-アンカーボルト
    レイヤ)・GL(0、F-立上りレイヤ)・底盤天端(底盤天端の絶対 Z、F-底盤レイヤ)。
    ``levels`` の並びは希望スタック順(上→下)で、最上段に基礎天端(アンカーボルト)、
    続いて立上り(GL)、底盤(底盤天端)を積むため基礎天端 → GL → 底盤天端 の順にする。
    アンカーボルトの高さ基準は基礎天端レベルが担う。
    """
    if not has_foundation(ifc_file):
        return None
    slab_top = resolve_slab_top_elevation(ifc_file)
    slab_top_offset = slab_top if slab_top is not None else 0.0
    # 基礎天端は立上り天端。立上りが無い基礎は底盤天端にフォールバックする。
    foundation_top = resolve_foundation_top_elevation(ifc_file)
    foundation_top_offset = (
        foundation_top if foundation_top is not None else slab_top_offset)
    return {
        'name': STORY_FOUNDATION,
        'suffix': FOUNDATION_SUFFIX,
        'elevation': 0.0,
        'levels': [
            {'type': LEVEL_FOUNDATION_TOP, 'offset': foundation_top_offset,
             'layer': LAYER_FOUNDATION_ANCHOR},
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

    最後に ``merge_wall_commands`` で、同一直線上にあり同一断面形状(壁厚・高さ基準)
    の立上りを 1 本の壁に統合する(ホームズ君 IFC では通り芯の交点等で立上りが細かく
    分断されているため、できるだけマージした形状で壁を作る)。
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
    return merge_wall_commands(commands)


def _wall_section_key(wall: WallCommand) -> tuple[object, ...]:
    """立上りの断面形状(統合可否)を表すキー。

    レイヤ・クラス・壁厚・下端/上端の高さ基準(story_offset・level・offset)が
    すべて一致する立上り同士だけを統合対象にする。offset は実 Z 由来の浮動小数
    のため許容値で丸める(``_WALL_MERGE_DIST_TOL`` = 1mm)。
    """
    bottom = wall['bottom_bound']
    top = wall['top_bound']
    return (
        wall['layer'], wall['class'], round(wall['thickness'], 3),
        bottom['story_offset'], bottom['level'],
        round(bottom['offset'] / _WALL_MERGE_DIST_TOL),
        top['story_offset'], top['level'],
        round(top['offset'] / _WALL_MERGE_DIST_TOL),
    )


def _walls_connected_collinear(a: WallCommand, b: WallCommand) -> bool:
    """立上り a・b が同一直線上にあり、区間が重なる/接触するか。

    a の壁芯を基準線とし、(1) b の方向が a と平行、(2) b の端点が a の直線上
    (直交距離 ≈ 0)、(3) a の区間 [0, len_a] と b の射影区間が重なる/接触する、
    の 3 条件をすべて満たすとき True(いずれも ``_WALL_MERGE_*_TOL`` の許容内)。
    """
    ax1, ay1 = a['start']
    ax2, ay2 = a['end']
    bx1, by1 = b['start']
    bx2, by2 = b['end']
    dax, day = ax2 - ax1, ay2 - ay1
    la = math.hypot(dax, day)
    dbx, dby = bx2 - bx1, by2 - by1
    lb = math.hypot(dbx, dby)
    if la <= 0.0 or lb <= 0.0:
        return False
    ux, uy = dax / la, day / la
    # (1) 単位方向ベクトルの外積(= sin 角)で平行判定
    if abs(ux * (dby / lb) - uy * (dbx / lb)) > _WALL_MERGE_ANGLE_TOL:
        return False
    # (2) b の始点の a 直線からの直交距離(平行なら b の全点が同距離)
    if abs(ux * (by1 - ay1) - uy * (bx1 - ax1)) > _WALL_MERGE_DIST_TOL:
        return False
    # (3) b を a 方向に射影した区間が [0, la] と重なる/接触するか
    tb1 = ux * (bx1 - ax1) + uy * (by1 - ay1)
    tb2 = ux * (bx2 - ax1) + uy * (by2 - ay1)
    b_lo, b_hi = min(tb1, tb2), max(tb1, tb2)
    if b_hi < -_WALL_MERGE_DIST_TOL or b_lo > la + _WALL_MERGE_DIST_TOL:
        return False
    return True


def _merge_wall_group(walls: list[WallCommand]) -> list[WallCommand]:
    """同一断面の立上り群のうち、同一直線上で連続するものを 1 本に統合する。

    Union-Find で連結成分(同一直線上で重なる/接触する立上りの連鎖)にまとめ、
    各成分を先頭の壁芯方向へ全端点を射影した最小〜最大区間の 1 本にする。
    成分の代表は最小インデックス、出力は代表インデックス昇順で入力順に準ずる。
    """
    n = len(walls)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if _walls_connected_collinear(walls[i], walls[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    merged: list[WallCommand] = []
    for root in sorted(components):
        members = [walls[i] for i in components[root]]
        if len(members) == 1:
            merged.append(members[0])
            continue
        base = members[0]
        ax1, ay1 = base['start']
        ax2, ay2 = base['end']
        la = math.hypot(ax2 - ax1, ay2 - ay1)
        ux, uy = (ax2 - ax1) / la, (ay2 - ay1) / la
        ts = [ux * (px - ax1) + uy * (py - ay1)
              for wall in members for px, py in (wall['start'], wall['end'])]
        t_lo, t_hi = min(ts), max(ts)
        command: WallCommand = {
            'layer': base['layer'],
            'class': base['class'],
            'start': [ax1 + ux * t_lo, ay1 + uy * t_lo],
            'end': [ax1 + ux * t_hi, ay1 + uy * t_hi],
            'thickness': base['thickness'],
            'bottom_bound': base['bottom_bound'],
            'top_bound': base['top_bound'],
        }
        merged.append(command)
    return merged


def merge_wall_commands(walls: list[WallCommand]) -> list[WallCommand]:
    """立上りの wall 命令を、同一直線上・同一断面のもの同士で統合する。

    基礎の立上りはホームズ君 IFC 上では通り芯の交点等で細かく分断されているため、
    そのまま描くと壁オブジェクトが多数に分かれる。同じ断面形状(壁厚・高さ基準)で
    同一直線上に連続する立上りを 1 本の壁にまとめ、できるだけ分断のない形状にする。

    断面キー(``_wall_section_key``)ごとにグループ化してから ``_merge_wall_group``
    で統合する。断面が異なる(壁厚・高さの違う)立上りや、同一直線上でも隙間がある
    立上り、平行だが別の線上にある立上りは統合しない。統合はグループ化・グループ内
    処理とも入力順に対して決定的で、命令の並び順に依存しない結果になる。
    """
    groups: dict[tuple[object, ...], list[WallCommand]] = {}
    order: list[tuple[object, ...]] = []
    for wall in walls:
        key = _wall_section_key(wall)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(wall)
    result: list[WallCommand] = []
    for key in order:
        result.extend(_merge_wall_group(groups[key]))
    return result


def _wall_intersection(
    a: WallCommand, b: WallCommand,
) -> tuple[float, float, bool, bool] | None:
    """立上り a・b の壁芯の交点と、その交点が各壁芯の端点か内部かを返す。

    Returns: (交点 x, 交点 y, a の端点で交わるか, b の端点で交わるか)。
    平行(交点が定まらない)・区間外で交わる立上りは None。同一直線上(平行)の
    立上りは merge_wall_commands が扱うためここでは結合対象にしない(None を返す)。

    **端点許容は相手壁の半分の壁厚を含める**。ホームズ君 IFC の立上りは直交する
    相手壁の**外面まで**モデル化されるため(コーナーで各壁が相手の芯を半壁厚だけ
    越えて/手前で終わる)、壁芯どうしの交点は各壁の端から半壁厚ほど離れた位置に
    来る。1mm の固定許容では外周コーナー(L)が「両方とも内部で交わる」= X 結合と
    誤判定され、VW の JoinWalls がコーナーを繋がない。各壁の端点許容を
    「相手壁の半壁厚 + ``_JOIN_ENDPOINT_TOL``」を壁芯長で割った割合にすることで、
    相手の外面で終わる(または手前で止まる)コーナーを正しく端点交差(L/T)と
    判定し、区間判定でも取りこぼさない。
    """
    ax1, ay1 = a['start']
    ax2, ay2 = a['end']
    bx1, by1 = b['start']
    bx2, by2 = b['end']
    rx, ry = ax2 - ax1, ay2 - ay1
    sx, sy = bx2 - bx1, by2 - by1
    la = math.hypot(rx, ry)
    lb = math.hypot(sx, sy)
    if la <= 0.0 or lb <= 0.0:
        return None
    rxs = rx * sy - ry * sx
    # 平行/同一直線: 交点が定まらないため結合対象にしない
    if abs(rxs) <= _WALL_MERGE_ANGLE_TOL * la * lb:
        return None
    qx, qy = bx1 - ax1, by1 - ay1
    t = (qx * sy - qy * sx) / rxs
    u = (qx * ry - qy * rx) / rxs
    # a の端点許容は相手 b の半壁厚(a は b の外面で終端しうる)、b は a の半壁厚。
    frac_a = (b['thickness'] / 2.0 + _JOIN_ENDPOINT_TOL) / la
    frac_b = (a['thickness'] / 2.0 + _JOIN_ENDPOINT_TOL) / lb
    # 交点が両壁芯の区間内(端点許容込み)にあるか
    if t < -frac_a or t > 1.0 + frac_a:
        return None
    if u < -frac_b or u > 1.0 + frac_b:
        return None
    px = ax1 + t * rx
    py = ay1 + t * ry
    a_at_end = t <= frac_a or t >= 1.0 - frac_a
    b_at_end = u <= frac_b or u >= 1.0 - frac_b
    return px, py, a_at_end, b_at_end


def _line_dir(wall: WallCommand) -> tuple[float, float, float]:
    """立上りの壁芯方向ベクトル (dx, dy) と長さを返す。"""
    x1, y1 = wall['start']
    x2, y2 = wall['end']
    dx, dy = x2 - x1, y2 - y1
    return dx, dy, math.hypot(dx, dy)


def _wall_top(wall: WallCommand) -> float:
    """立上りの天端高さの比較値(top_bound の offset)を返す。

    基礎の立上りはすべて同じレベル(1 階横架材天端・story_offset=1)に上端を
    バインドするため、offset だけで天端の絶対高さを比較できる。offset が大きい
    立上りほど天端が高い。
    """
    return wall['top_bound']['offset']


def _wall_point_at_end(wall: WallCommand, px: float, py: float) -> bool:
    """壁芯上の点 (px, py) が立上り ``wall`` の端点とみなせるか。

    始点からの正規化パラメータ t(0=始点・1=終点)を求め、端からの距離が
    半壁厚 + ``_JOIN_ENDPOINT_TOL`` 以内なら端点とみなす(立上りは相手壁の外面まで
    伸びるためコーナーの交点が壁の端から半壁厚離れる。_wall_intersection と同じ考え)。
    """
    x1, y1 = wall['start']
    x2, y2 = wall['end']
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return True
    t = ((px - x1) * dx + (py - y1) * dy) / (length * length)
    frac = (wall['thickness'] / 2.0 + _JOIN_ENDPOINT_TOL) / length
    return t <= frac or t >= 1.0 - frac


def _wall_junctions(
    walls: list[WallCommand],
) -> list[tuple[tuple[float, float], list[int]]]:
    """交差する立上りのペアから、同一交点に集まる立上りの集合を作る。

    全ペアの壁芯交点(``_wall_intersection``)を求め、交点が
    ``_JOIN_CLUSTER_TOL`` 以内で近いものを 1 つのジャンクションにまとめる
    (union-find)。3 本以上の立上りが 1 点に集まる場合、その 3 本の全ペアの交点は
    数学的に同一点になるため 1 つのジャンクションに束ねられる。

    Returns: ``(交点 (x, y), その点に集まる立上りの walls 内インデックス昇順)`` の
    リスト。ジャンクションは代表エッジのインデックス昇順で並び、入力順に対して決定的。
    """
    edges: list[tuple[int, int, float, float]] = []
    n = len(walls)
    for i in range(n):
        for j in range(i + 1, n):
            if walls[i]['layer'] != walls[j]['layer']:
                continue
            result = _wall_intersection(walls[i], walls[j])
            if result is None:
                continue
            px, py, _ae, _be = result
            edges.append((i, j, px, py))

    m = len(edges)
    parent = list(range(m))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for p in range(m):
        for q in range(p + 1, m):
            if math.hypot(edges[p][2] - edges[q][2],
                          edges[p][3] - edges[q][3]) <= _JOIN_CLUSTER_TOL:
                rp, rq = find(p), find(q)
                if rp != rq:
                    parent[max(rp, rq)] = min(rp, rq)

    clusters: dict[int, list[int]] = {}
    for p in range(m):
        clusters.setdefault(find(p), []).append(p)

    junctions: list[tuple[tuple[float, float], list[int]]] = []
    for root in sorted(clusters):
        eids = clusters[root]
        indices: set[int] = set()
        for eid in eids:
            indices.add(edges[eid][0])
            indices.add(edges[eid][1])
        rep = edges[min(eids)]
        junctions.append(((rep[2], rep[3]), sorted(indices)))
    return junctions


def _emit_junction_joins(
    walls: list[WallCommand], indices: list[int], point: tuple[float, float],
) -> list[WallJoinCommand]:
    """1 つのジャンクション(同一交点に集まる立上り)の壁結合命令を組み立てる。

    - **天端高さによる capped**(要件1): 結合する 2 壁の天端高さが異なるときは
      低いほうの壁を高いほうに結合し(低い壁を ``a``)、``capped=True`` にする。
      同じ高さなら ``capped=False``。
    - **3 本以上の交点**(要件2): 天端高さが最も高い立上りをバックボーンにして
      まず ``capped=False`` で繋ぎ、それより低い立上りを ``capped=True`` で繋ぐ。
      命令は ``capped=False`` を先に並べる。
    - **3 本以上の端点コーナー**(要件3): はじめの 2 本を L で繋ぎ、それ以降の
      立上りを T で繋ぐ(バックボーンへ突き当てる)。
    """
    px, py = point
    at_end = {idx: _wall_point_at_end(walls[idx], px, py) for idx in indices}
    tops = {idx: _wall_top(walls[idx]) for idx in indices}
    interiors = [idx for idx in indices if not at_end[idx]]
    ends = [idx for idx in indices if at_end[idx]]

    def height_order(idx: int) -> tuple[float, int]:
        # 天端高さ降順・インデックス昇順(バックボーンに最も高い立上りを選ぶ)
        return (-tops[idx], idx)

    def make_lx(low_or_other: int, root: int, join_type: int) -> WallJoinCommand:
        """L / X 結合の命令を作る。``root`` は高い(または同高でルート)側。"""
        capped = abs(tops[low_or_other] - tops[root]) > _WALL_HEIGHT_TOL
        if capped and tops[low_or_other] > tops[root]:
            a, b = root, low_or_other       # 低いほうを a(高いほうに結合)
        elif capped:
            a, b = low_or_other, root        # low_or_other が低い → a
        else:
            a, b = root, low_or_other        # 同高: ルートを a(既存挙動)
        return {'a': a, 'b': b, 'point': [px, py],
                'join_type': join_type, 'capped': capped}

    def make_t(stem: int, through: int) -> WallJoinCommand:
        """T 結合の命令を作る。stem(端点側=延長される)を ``a`` にする。"""
        capped = abs(tops[stem] - tops[through]) > _WALL_HEIGHT_TOL
        return {'a': stem, 'b': through, 'point': [px, py],
                'join_type': _JOIN_T, 'capped': capped}

    def pick_through(stem: int, candidates: list[int]) -> int:
        """stem が T 結合する通し壁を candidates から選ぶ。

        stem に最も直交する(単位方向ベクトルの外積 |sin| が最大の)壁を選び、
        同点なら天端が高いほう、さらに同点ならインデックスの小さいほうを選ぶ。
        """
        sdx, sdy, sl = _line_dir(walls[stem])
        best = candidates[0]
        best_key: tuple[float, float, int] | None = None
        for c in candidates:
            cdx, cdy, cl = _line_dir(walls[c])
            perp = (abs(sdx * cdy - sdy * cdx) / (sl * cl)
                    if sl > 0.0 and cl > 0.0 else 0.0)
            key = (perp, tops[c], -c)
            if best_key is None or key > best_key:
                best, best_key = c, key
        return best

    commands: list[WallJoinCommand] = []
    if interiors:
        # 交点(T/X): 通し壁(内部で交わる壁)をバックボーンにする
        ordered_int = sorted(interiors, key=height_order)
        root = ordered_int[0]
        for other in ordered_int[1:]:
            commands.append(make_lx(other, root, _JOIN_X))
        for stem in sorted(ends, key=height_order):
            commands.append(make_t(stem, pick_through(stem, interiors)))
    else:
        # 端点コーナー: 天端高さ降順ではじめの 2 本を L、それ以降を T
        ordered = sorted(ends, key=height_order)
        root = ordered[0]
        if len(ordered) >= 2:
            commands.append(make_lx(ordered[1], root, _JOIN_L))
        for stem in ordered[2:]:
            commands.append(make_t(stem, pick_through(stem, ordered[:2])))

    # 要件2: capped=False(高い立上り同士)を先に、capped=True を後に並べる
    commands.sort(key=lambda c: c['capped'])
    return commands


def build_wall_join_commands(walls: list[WallCommand]) -> list[WallJoinCommand]:
    """立上り(壁)命令から、交差する壁同士を結合する wall_join 命令を組み立てる。

    ``walls`` は ``build_wall_commands`` が返す(マージ済みの)wall 命令リストで、
    その並び順が document の ``walls`` と一致するため、命令の ``a`` / ``b`` は
    そのインデックスをそのまま指す。壁芯が交差する立上りを同一交点ごとに
    ジャンクションにまとめ(``_wall_junctions``)、ジャンクションごとに結合命令を
    組み立てる(``_emit_junction_joins``。要件1〜3 の高さ・capped・L/T/X 判定)。
    同一直線上(平行)の立上りは merge_wall_commands が 1 本に統合済みで結合対象に
    しない。判定は入力順に対して決定的。
    """
    commands: list[WallJoinCommand] = []
    for point, indices in _wall_junctions(walls):
        if len(indices) < 2:
            continue
        commands.extend(_emit_junction_joins(walls, indices, point))
    return commands


def build_slab_commands(ifc_file: ifcopenshell.file) -> list[SlabCommand]:
    """基礎の底盤・地中梁から slab 命令のリストを組み立てる。

    平面外形を底盤天端レベルにセンタリングして格納し、天端の絶対 Z を elevation に
    格納する(描画フェーズが SetSlabHeight でスラブの天端高さとして設定する)。
    加えて天端を底盤天端レベルにバインドする(bound.offset は実天端 Z と底盤天端の
    絶対 Z の差)。基礎ストーリは GL=0 のため elevation はストーリ基準高さとも一致する。
    地中梁は底盤の下にぶら下がるため天端が底盤天端より低く offset が負値になる。
    スラブ厚は SetSlabHeight では設定できず(高さを設定する関数のため)スラブ
    スタイルが決めるので、命令には厚みを持たせない。
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
        top_abs, _thickness = _z_top_and_thickness(solid)
        boundary = [[x - center_x, y - center_y] for x, y in _footprint(solid)]
        bound: StoryBoundCommand = {
            'story_offset': 0, 'level': LEVEL_SLAB_TOP,
            'offset': top_abs - slab_top_abs}
        commands.append({
            'layer': LAYER_FOUNDATION_SLAB,
            'class': CLASS_FOUNDATION_SLAB,
            'boundary': boundary,
            'elevation': top_abs,
            'bound': bound,
        })
    return commands
