"""基礎(立上り・底盤・地中梁、IfcFooting/IfcSlab)の解析と命令の組み立て。vs 非依存。

ホームズ君 IFC の基礎要素を 3 種に分類して別オブジェクトに変換する。

- 立上り(基礎梁): ``Name`` が ``基礎梁`` で始まる IfcFooting。壁オブジェクト
  (wall 命令)にする。下端は基礎(自階)の GL、上端は 1 階(上階)の横架材天端に
  バインドする。
- 底盤(基礎底盤・布基礎底盤・独立基礎底盤): ``Name`` に ``底盤`` を含む
  IfcSlab/IfcFooting。スラブオブジェクト(slab 命令)にする。天端を基礎の
  底盤天端レベルにバインドする。
- 地中梁(地中梁・部分地中梁): ``Name`` に ``地中梁`` を含む IfcFooting。
  台形断面のため単一のスラブオブジェクトでは描けない。底盤(基礎底盤)の
  コンクリートに 3D ソリッド(モディファイア=``ModifierCommand``)として
  噛み合わせて実形状を表す。各地中梁の台形プリズムを、平面で重なる底盤スラブ
  命令の ``modifiers`` に持たせる(単独のスラブ命令にはしない)。

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
    ColumnCommand,
    ModifierCommand,
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
    LAYER_FOUNDATION_FLOOR_POST,
    LAYER_FOUNDATION_SLAB,
    LAYER_FOUNDATION_WALL,
    LEVEL_BEAM_TOP,
    LEVEL_FLOOR_POST,
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

# 自由端の終端柱(柱芯)を探す許容値 (mm)。立上りの自由端は、端部を受ける管柱の
# 柱芯より外側に、その上に載る土台の半材せい(土台幅の半分、約 50mm)ぶんだけ
# 長く入力されていることがある(半島状の立上り)。柱芯を基準に半壁厚だけ延長する
# ため、自由端の内側にある終端柱を探して基準点を柱芯へ寄せる。
# ``_FREE_END_COLUMN_ALONG_TOL``(沿軸距離)は土台の半材せい(≤ ~75mm)を余裕を
# もって覆い、隣接する 1 モジュール(≥455mm)先の柱は拾わない値にする。
# ``_FREE_END_COLUMN_PERP_TOL`` は柱芯が壁芯線から外れていても許容する、半壁厚に
# 加える直交距離。
_FREE_END_COLUMN_ALONG_TOL = 150.0
_FREE_END_COLUMN_PERP_TOL = 20.0

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
    レイヤ)・GL(0、F-立上りレイヤ)・床束(底盤天端の絶対 Z、F-床束レイヤ)・
    底盤天端(底盤天端の絶対 Z、F-底盤レイヤ)。``levels`` の並びは希望スタック順
    (上→下)で、最上段に基礎天端(アンカーボルト)、続いて立上り(GL)、床束、
    底盤(底盤天端)を積むため 基礎天端 → GL → 床束 → 底盤天端 の順にする。
    アンカーボルトの高さ基準は基礎天端レベル、床束(シンボル)の高さ基準は床束
    レベル(底盤上端に揃える)が担う。
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
            # 床束は基礎底盤上端(底盤天端)に立つため高さは底盤天端に揃える。
            {'type': LEVEL_FLOOR_POST, 'offset': slab_top_offset,
             'layer': LAYER_FOUNDATION_FLOOR_POST},
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


def build_wall_commands(
    ifc_file: ifcopenshell.file,
    columns: list[ColumnCommand] | None = None,
) -> list[WallCommand]:
    """基礎の立上り(基礎梁)から wall 命令のリストを組み立てる。

    壁芯は配置原点からプロファイル中心線(押し出し方向)に沿った線。壁厚は矩形断面
    の幅(XDim)、上下端は実形状の絶対 Z。下端は基礎の GL、上端は 1 階の横架材天端に
    バインドし、offset はそれぞれの実 Z とバインド先レベルの絶対 Z の差。

    ``merge_wall_commands`` で、同一直線上にあり同一断面形状(壁厚・高さ基準)の
    立上りを 1 本の壁に統合する(ホームズ君 IFC では通り芯の交点等で立上りが細かく
    分断されているため、できるだけマージした形状で壁を作る)。最後に
    ``_extend_free_wall_ends`` で、他の立上りと交差しない端点を柱芯を基準に半壁厚だけ
    外側へ延長して実形状に合わせる。柱芯の判定に柱命令(``columns``)を使うため、
    ``build_document`` が組み立てた columns を渡す(未指定なら柱芯へ寄せず端点から
    半壁厚延長する。半島状の立上りの自由端が土台の半材せいぶん長くなるのを防ぐ
    ``_extend_free_wall_ends`` 参照)。
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
    return _extend_free_wall_ends(merge_wall_commands(commands), columns)


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


def _terminal_column_base(
    px: float, py: float, ux: float, uy: float, half: float,
    columns: list[ColumnCommand],
) -> tuple[float, float]:
    """自由端 (px, py) の終端柱(柱芯)を壁芯上に射影した基準点を返す。

    立上りの自由端は、端部を受ける管柱の**柱芯**より外側に(その上に載る土台の
    半材せいぶん)長く入力されていることがある(半島状の立上り)。柱芯を基準に
    半壁厚だけ延長するため、自由端の内側(外向き ``(ux, uy)`` の逆側)にある終端柱を
    探し、その柱芯を壁芯へ射影した点を返す。終端柱が見つからなければ自由端をそのまま
    返す(柱芯 = 自由端とみなし、従来どおり半壁厚だけ延長される)。

    ``(ux, uy)`` は自由端で壁の外側を向く単位ベクトル(始端の自由端なら始端向き、
    終端の自由端なら終端向き)。終端柱は、柱芯が壁芯線に近く(直交距離 ≤
    半壁厚 + ``_FREE_END_COLUMN_PERP_TOL``)、自由端から壁芯の内側に沿って
    ``_FREE_END_COLUMN_ALONG_TOL`` 以内にある柱のうち自由端に最も近いもの。判定は
    列挙順に依存しない(沿軸距離が最小の柱を選ぶ)。
    """
    best_t: float | None = None
    for col in columns:
        cx, cy = col['position'][0], col['position'][1]
        dx, dy = cx - px, cy - py
        t = dx * ux + dy * uy             # 外向きの沿軸成分(内側の柱は負)
        perp = abs(dx * (-uy) + dy * ux)  # 壁芯線からの直交距離
        if perp > half + _FREE_END_COLUMN_PERP_TOL:
            continue
        # 自由端の内側(t<0)または端点付近(t≈0)にある柱だけを対象にする
        if t > _JOIN_ENDPOINT_TOL or t < -_FREE_END_COLUMN_ALONG_TOL:
            continue
        if best_t is None or abs(t) < abs(best_t):
            best_t = t
    if best_t is None:
        return px, py
    return px + ux * best_t, py + uy * best_t


def _extend_free_wall_ends(
    walls: list[WallCommand],
    columns: list[ColumnCommand] | None = None,
) -> list[WallCommand]:
    """他の立上りと交差しない端点を、柱芯を基準に半壁厚だけ外側へ延長する。

    ホームズ君 IFC では、他の立上りと交差しない立上りの端点は基本的に**柱芯までの
    長さ**で入力されているが、実際の基礎立上りはそこから**半壁厚だけ長い**(端面が
    柱芯より半壁厚外側にある)。交差する端点は相手壁の外面までモデル化済みで、
    コーナーで既に半壁厚のオーバーハングを持つ(``_wall_intersection`` の端点許容
    参照)ため触らず、どの立上りとも交差しない端点だけを ``thickness/2`` 延長して
    実形状に合わせる。延長は壁芯方向(自分の軸)に沿って外側(始点は始点側・終点は
    終点側)へ行うため、交差しない側並び・平行の関係を新たに作らない。

    ただし半島状の立上りの自由端は、端部を受ける管柱の柱芯より外側に、その上に載る
    土台の半材せい(約 50mm)ぶんだけ長く入力されていることがある。この端点をその
    まま半壁厚延長すると柱芯から「半材せい + 半壁厚」ぶん突き出して長くなりすぎる。
    そこで ``columns``(柱命令)が与えられたときは、自由端ごとに終端柱の柱芯
    (``_terminal_column_base``)を探して基準点を柱芯へ寄せてから半壁厚延長する
    (柱芯 + 半壁厚に揃える)。柱芯が見つからない自由端は従来どおり端点から半壁厚
    延長する。

    交差の有無は ``_wall_intersection`` で判定する(交点が壁芯の端点にあれば
    ``a_at_end`` / ``b_at_end``)。交点に最も近い端点を「交差する端点」として除外し、
    残った端点だけを延長する。判定は入力順に対して決定的で命令の並び順に依存しない。
    """
    cols: list[ColumnCommand] = columns or []
    n = len(walls)
    # 各壁の始点・終点が他の立上りとの交点に関与するか
    start_joined = [False] * n
    end_joined = [False] * n

    def mark(idx: int, px: float, py: float) -> None:
        x1, y1 = walls[idx]['start']
        x2, y2 = walls[idx]['end']
        if math.hypot(x1 - px, y1 - py) <= math.hypot(x2 - px, y2 - py):
            start_joined[idx] = True
        else:
            end_joined[idx] = True

    for i in range(n):
        for j in range(i + 1, n):
            if walls[i]['layer'] != walls[j]['layer']:
                continue
            result = _wall_intersection(walls[i], walls[j])
            if result is None:
                continue
            px, py, a_at_end, b_at_end = result
            if a_at_end:
                mark(i, px, py)
            if b_at_end:
                mark(j, px, py)

    extended: list[WallCommand] = []
    for i, wall in enumerate(walls):
        x1, y1 = wall['start']
        x2, y2 = wall['end']
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0.0:
            extended.append(wall)
            continue
        half = wall['thickness'] / 2.0
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        if start_joined[i]:
            start = [x1, y1]
        else:
            # 始端の自由端: 外向きは -軸方向。柱芯へ寄せてから半壁厚延長する。
            bx, by = _terminal_column_base(x1, y1, -ux, -uy, half, cols)
            start = [bx - ux * half, by - uy * half]
        if end_joined[i]:
            end = [x2, y2]
        else:
            # 終端の自由端: 外向きは +軸方向。柱芯へ寄せてから半壁厚延長する。
            bx, by = _terminal_column_base(x2, y2, ux, uy, half, cols)
            end = [bx + ux * half, by + uy * half]
        extended.append({
            'layer': wall['layer'],
            'class': wall['class'],
            'start': start,
            'end': end,
            'thickness': wall['thickness'],
            'bottom_bound': wall['bottom_bound'],
            'top_bound': wall['top_bound'],
        })
    return extended


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


# ピック点を交点から「残す側」へ寄せる際の、寄せ量を壁芯長に対して制限する上限。
# 交点〜遠い端点の距離にこの割合を掛けた値で寄せ量をクランプし、寄せた点が残す
# 区間を越えない・詰める端点(近い側)が最も近い端点のまま保たれるようにする。
_PICK_OFFSET_FRAC = 0.4


def _kept_side_pick(
    wall: WallCommand, jx: float, jy: float, offset: float,
) -> list[float]:
    """壁 ``wall`` の交点 (jx, jy) から「残す側」へ寄せた JoinWalls ピック点を返す。

    残す側 = 交点から**遠い**端点の方向。JoinWalls のピック点は各壁の「残す側の
    壁芯上の点」を指す必要がある。交点そのもの(両壁芯の交点)は相手壁の壁芯上にも
    乗るため「どちら側を残すか」が曖昧になり、VW が L 結合でコーナーを詰めず立上りが
    相手壁の外面まで伸びたまま残る(本不具合)。遠い端点方向へ ``offset`` だけ寄せた
    点にすることで残す区間を明示する。寄せ量は交点〜遠い端点の距離の
    ``_PICK_OFFSET_FRAC`` までにクランプし、控えめに寄せて詰める端点(近い側)が最も
    近い端点のまま保たれるようにする(遠い端点が最寄りになると VW が残す/詰める側を
    取り違えるのを防ぐ)。壁芯長が 0 の場合は交点をそのまま返す。
    """
    x1, y1 = wall['start']
    x2, y2 = wall['end']
    d1 = math.hypot(x1 - jx, y1 - jy)
    d2 = math.hypot(x2 - jx, y2 - jy)
    fx, fy = (x2, y2) if d2 >= d1 else (x1, y1)
    dx, dy = fx - jx, fy - jy
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return [jx, jy]
    step = min(offset, length * _PICK_OFFSET_FRAC) / length
    return [jx + dx * step, jy + dy * step]


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
    # ピック点の寄せ量。交点に集まる立上りの最大壁厚を使い、相手壁の footprint
    # (半壁厚)を確実に越えて残す側に寄せる(交点は相手壁芯上にあり曖昧なため)。
    pick_offset = max(walls[idx]['thickness'] for idx in indices)

    def picks(a: int, b: int) -> tuple[list[float], list[float]]:
        return (_kept_side_pick(walls[a], px, py, pick_offset),
                _kept_side_pick(walls[b], px, py, pick_offset))

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
        pick_a, pick_b = picks(a, b)
        return {'a': a, 'b': b, 'point': [px, py],
                'pick_a': pick_a, 'pick_b': pick_b,
                'join_type': join_type, 'capped': capped}

    def make_t(stem: int, through: int) -> WallJoinCommand:
        """T 結合の命令を作る。stem(端点側=延長される)を ``a`` にする。"""
        capped = abs(tops[stem] - tops[through]) > _WALL_HEIGHT_TOL
        pick_a, pick_b = picks(stem, through)
        return {'a': stem, 'b': through, 'point': [px, py],
                'pick_a': pick_a, 'pick_b': pick_b,
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


def build_slab_commands(
    ifc_file: ifcopenshell.file,
    walls: list[WallCommand] | None = None,
) -> list[SlabCommand]:
    """基礎の底盤から slab 命令のリストを組み立てる(地中梁はモディファイアで表す)。

    平面外形を底盤天端レベルにセンタリングして格納し、天端の絶対 Z を elevation に
    格納する(描画フェーズが SetSlabHeight でスラブの天端高さとして設定する)。
    加えて天端を底盤天端レベルにバインドする(bound.offset は実天端 Z と底盤天端の
    絶対 Z の差)。基礎ストーリは GL=0 のため elevation はストーリ基準高さとも一致する。

    ``thickness`` は底盤(基礎底盤系)にだけ設定するスラブスタイルのコンクリート厚
    (mm、Z 方向の厚みを整数 mm に丸めた値)。描画フェーズがこの厚みからスラブ
    スタイルを選ぶ(``vw/footing.py`` 参照)。

    命令を組み立てた後、``merge_slab_commands`` で**同じ厚さ・同じ高さで連続する
    底盤**(基礎底盤系)を 1 枚のスラブに統合し、``align_slabs_to_wall_faces`` で
    底盤の外周を立上り(基礎梁)の**外面に合わせて外側へ広げる**(ホームズ君 IFC の
    底盤外形は立上りの壁心に一致しているため、外面まで半壁厚だけ広げる)。
    外面合わせに使う立上りは ``walls``(未指定なら ``build_wall_commands`` で組み立てる)。

    **地中梁**(台形断面)は単一のスラブでは描けないため、底盤コンクリートに噛み合う
    モディファイア(台形プリズム=``ModifierCommand``)にする(要件)。統合・外面合わせ
    まで済んだ底盤のうち、各地中梁の平面外形と重なる底盤の ``modifiers`` に振り分ける
    (``_attach_ground_beam_modifiers``)。地中梁を単独のスラブ命令にはしない。
    """
    slab_top = resolve_slab_top_elevation(ifc_file)
    slab_top_abs = slab_top if slab_top is not None else 0.0

    _, center_x, center_y = resolve_lines(ifc_file)

    commands: list[SlabCommand] = []
    for element in _iter_footing_elements(ifc_file):
        name = element.Name or ''
        if not _is_base_slab(name):
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
            'elevation': top_abs,
            'thickness': float(round(thickness)),
            'bound': bound,
            'modifiers': [],
        })
    if walls is None:
        walls = build_wall_commands(ifc_file)
    slabs = align_slabs_to_wall_faces(merge_slab_commands(commands), walls)
    modifiers = _build_ground_beam_modifiers(ifc_file, center_x, center_y)
    _attach_ground_beam_modifiers(slabs, modifiers)
    return slabs


def _build_ground_beam_modifiers(
    ifc_file: ifcopenshell.file, center_x: float, center_y: float,
) -> list[tuple[ModifierCommand, list[_Pt2]]]:
    """地中梁を台形プリズムのモディファイアに変換したリストを返す。

    各地中梁は水平押し出しの台形断面ソリッド。断面(``profile``)を幅軸 u・鉛直軸 v
    の 2D 頂点列に取り直し、押し出し方向の方位角(``azimuth``)と断面原点のワールド
    座標(``origin``、XY はセンタリング済み)を求める。返り値は
    ``(モディファイア命令, 平面外形)`` のリストで、平面外形は底盤への振り分け判定
    (``_attach_ground_beam_modifiers``)に使う(グリッド中心オフセット済み)。
    """
    result: list[tuple[ModifierCommand, list[_Pt2]]] = []
    for element in ifc_file.by_type('IfcFooting'):
        if not _is_ground_beam(element.Name or ''):
            continue
        solid = _world_solid(element)
        if solid is None:
            continue
        modifier = _ground_beam_modifier(solid, center_x, center_y)
        if modifier is None:
            continue
        footprint = [(x - center_x, y - center_y) for x, y in _footprint(solid)]
        result.append((modifier, footprint))
    return result


def _ground_beam_modifier(
    solid: _Solid, center_x: float, center_y: float,
) -> ModifierCommand | None:
    """地中梁の押し出しソリッドを台形プリズムのモディファイア命令にする。

    押し出し方向(梁の走る向き)の水平成分から方位角を求め、断面頂点を幅軸 u
    (走る向きを +90 度回した水平単位ベクトル ``w``)・鉛直軸 v(ワールド Z の差分)へ
    取り直す。断面原点(profile の (0,0)=ソリッド配置原点)の XY をセンタリングし、
    z は絶対値(梁下端の Z)にする。u 軸の取り方(``w`` = 走る向き +90 度)は描画
    フェーズの回転規約(``Rotate3D(90,0,0)`` → ``Rotate3D(0,0,azimuth+90)``)と一致
    させる。押し出し方向が水平でない(鉛直)ソリッドは地中梁でないため None。
    """
    (origin, lx, ly, _lz), extrude, depth, pts, _dims = solid
    run_len = math.hypot(extrude[0], extrude[1])
    if run_len <= 0.0:
        return None
    ux, uy = extrude[0] / run_len, extrude[1] / run_len
    azimuth = math.degrees(math.atan2(uy, ux))
    # 幅軸 w = 走る向きを +90 度回した水平単位ベクトル(描画の回転規約に一致)。
    wx, wy = -uy, ux
    ox, oy, oz = origin
    profile: list[list[float]] = []
    for u, v in pts:
        px = ox + lx[0] * u + ly[0] * v
        py = oy + lx[1] * u + ly[1] * v
        pz = oz + lx[2] * u + ly[2] * v
        u_off = (px - ox) * wx + (py - oy) * wy
        v_off = pz - oz
        profile.append([u_off, v_off])
    return {
        'profile': profile,
        'depth': float(depth),
        'origin': [ox - center_x, oy - center_y, oz],
        'azimuth': azimuth,
    }


def _polygon_centroid(pts: list[_Pt2]) -> _Pt2:
    """多角形頂点列の重心(頂点の相加平均)を返す。"""
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def _footprint_samples(pts: list[_Pt2]) -> list[_Pt2]:
    """平面外形の代表点(重心・各頂点・各辺の中点)を返す(振り分けの判定用)。"""
    samples: list[_Pt2] = [_polygon_centroid(pts)]
    samples.extend(pts)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        samples.append(((ax + bx) / 2.0, (ay + by) / 2.0))
    return samples


def _best_slab_for_footprint(
    footprint: list[_Pt2], slabs: list[SlabCommand],
) -> int | None:
    """地中梁の平面外形が最も重なる底盤スラブのインデックスを返す。無ければ None。

    地中梁の代表点(``_footprint_samples``)が各底盤の外形内に入る数を数え、最も多い
    底盤に振り分ける。どの底盤にも入らない(継目・下屋等で外形の外に出た)ときは、
    重心が最も近い底盤へフォールバックして取りこぼさない。底盤が無ければ None。
    """
    if not slabs:
        return None
    polys = [[(x, y) for x, y in slab['boundary']] for slab in slabs]
    samples = _footprint_samples(footprint)
    counts = [sum(1 for sx, sy in samples if _point_in_poly(sx, sy, poly))
              for poly in polys]
    best = max(range(len(polys)), key=lambda i: counts[i])
    if counts[best] > 0:
        return best
    # フォールバック: 重心が最も近い底盤
    cx, cy = _polygon_centroid(footprint)
    return min(range(len(polys)),
               key=lambda i: math.dist((cx, cy), _polygon_centroid(polys[i])))


def _attach_ground_beam_modifiers(
    slabs: list[SlabCommand],
    modifiers: list[tuple[ModifierCommand, list[_Pt2]]],
) -> None:
    """地中梁モディファイアを、平面で重なる底盤スラブの ``modifiers`` に振り分ける。

    各モディファイアを最も重なる底盤(``_best_slab_for_footprint``)に付ける。底盤が
    1 枚も無い場合は付けられないため捨てる(地中梁だけで底盤の無い基礎は稀)。判定は
    入力順に対して決定的。
    """
    for modifier, footprint in modifiers:
        index = _best_slab_for_footprint(footprint, slabs)
        if index is None:
            continue
        slabs[index]['modifiers'].append(modifier)


# --- 底盤のマージ・外面合わせ ---
# 隣接判定・同一直線判定・共線判定の許容値 (mm)。壁マージと同じ 1mm。
_SLAB_MERGE_TOL = 1.0
# 平行判定に使う単位方向ベクトルの外積(sin 角)の許容値。
_SLAB_ANGLE_TOL = 1e-3
# 交点計算で頂点を丸める小数桁(1e-4 mm = 0.1 ミクロン)。異なる底盤が共有する
# 頂点・交点を同一視して境界追跡でつなぐため。
_SLAB_ROUND = 4
# 境界辺の分類で「辺のすぐ右(外側)」を判定する法線方向のサンプル距離 (mm)。
# 部材寸法(mm 単位)より十分小さく、頂点丸め(0.1 ミクロン)より十分大きい。
_SLAB_SIDE_EPS = 1e-2

# 2D 座標(平面点)
_Pt2 = tuple[float, float]


def _slab_merge_key(slab: SlabCommand) -> tuple[object, ...]:
    """底盤の統合可否を表すキー。レイヤ・クラス・コンクリート厚・高さ基準が
    すべて一致する底盤同士だけを統合対象にする(offset は許容値で丸める)。"""
    thickness = slab['thickness']
    bound = slab['bound']
    return (
        slab['layer'], slab['class'], round(thickness or 0.0, 3),
        bound['story_offset'], bound['level'],
        round(bound['offset'] / _SLAB_MERGE_TOL),
    )


def _shoelace_signed(pts: list[_Pt2]) -> float:
    """符号付き面積(CCW で正、CW で負)を返す。"""
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _round_pt(pt: _Pt2) -> _Pt2:
    return (round(pt[0], _SLAB_ROUND), round(pt[1], _SLAB_ROUND))


def _clean_ring(boundary: list[list[float]]) -> list[_Pt2]:
    """境界を丸めた頂点列にし、末尾の閉じ重複・連続する同一点を除く。"""
    pts = [_round_pt((x, y)) for x, y in boundary]
    out: list[_Pt2] = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _point_in_poly(x: float, y: float, poly: list[_Pt2]) -> bool:
    """点 (x, y) が単純多角形 poly の内部(境界は含めない近似)にあるか。

    水平レイキャスト(半開ルール)による判定。呼び出し側は辺から法線方向へ
    ``_SLAB_SIDE_EPS`` ずらした点を渡すため、辺ちょうどの縮退は問題にならない。
    """
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xint = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < xint:
                inside = not inside
        j = i
    return inside


def _seg_split_points(a: _Pt2, b: _Pt2, c: _Pt2, d: _Pt2) -> list[_Pt2]:
    """線分 ab を分割すべき点(線分 cd との交点)を ab 上の点として返す。

    非平行なら区間内の交点、共線なら cd の端点を ab 上へ射影した点(区間内)を
    返す。これで交差・T 字接合・共線オーバーラップの分割点をすべて拾う。
    """
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denom = rx * sy - ry * sx
    r_len = math.hypot(rx, ry)
    s_len = math.hypot(sx, sy)
    if r_len <= 0.0 or s_len <= 0.0:
        return []
    out: list[_Pt2] = []
    if abs(denom) > _SLAB_ANGLE_TOL * r_len * s_len:
        t = ((cx - ax) * sy - (cy - ay) * sx) / denom
        u = ((cx - ax) * ry - (cy - ay) * rx) / denom
        if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
            out.append((ax + t * rx, ay + t * ry))
        return out
    # 平行: 共線ならオーバーラップ端点を分割点にする
    if abs((cx - ax) * ry - (cy - ay) * rx) > _SLAB_MERGE_TOL * r_len:
        return []
    for px, py in (c, d):
        t = ((px - ax) * rx + (py - ay) * ry) / (r_len * r_len)
        if -1e-9 <= t <= 1.0 + 1e-9:
            out.append((ax + t * rx, ay + t * ry))
    return out


def _split_edge(
    a: _Pt2, b: _Pt2, cuts: set[_Pt2],
) -> list[tuple[_Pt2, _Pt2]]:
    """有向辺 a→b を分割点 cuts で細分した有向部分辺のリストを返す。"""
    ax, ay = a
    bx, by = b
    rx, ry = bx - ax, by - ay
    length2 = rx * rx + ry * ry
    params: dict[_Pt2, float] = {}
    for pt in [a, b, *cuts]:
        rp = _round_pt(pt)
        t = (((rp[0] - ax) * rx + (rp[1] - ay) * ry) / length2
             if length2 > 0.0 else 0.0)
        if -1e-9 <= t <= 1.0 + 1e-9:
            params[rp] = t
    ordered = sorted(params, key=lambda p: params[p])
    return [(ordered[i], ordered[i + 1])
            for i in range(len(ordered) - 1) if ordered[i] != ordered[i + 1]]


def _polygon_union(polys: list[list[_Pt2]]) -> list[list[_Pt2]] | None:
    """任意向きの単純多角形群の和(union)の境界ループを返す。開ループなら None。

    各多角形を CCW 向き(内部が左)に揃え、全辺を他辺との交点で細分する。細分した
    有向辺のうち、辺のすぐ右(外側)がどの多角形にも含まれないものだけを union の
    境界として残す(共有辺は両隣の多角形が右側に来て打ち消され、外周辺だけ残る)。
    残った辺をつないでループにし、共線の中間点を除いて返す。CCW(正面積)ループが
    外形、CW(負面積)ループが穴。呼び出し側が外形 1 個・穴無しの成分だけ統合する。
    """
    oriented = [p if _shoelace_signed(p) >= 0.0 else p[::-1] for p in polys]
    directed: list[tuple[_Pt2, _Pt2]] = []
    for poly in oriented:
        n = len(poly)
        for i in range(n):
            directed.append((poly[i], poly[(i + 1) % n]))

    m = len(directed)
    cuts: list[set[_Pt2]] = [set() for _ in range(m)]
    for i in range(m):
        a, b = directed[i]
        for j in range(m):
            if i == j:
                continue
            c, d = directed[j]
            for pt in _seg_split_points(a, b, c, d):
                cuts[i].add(_round_pt(pt))

    boundary: list[tuple[_Pt2, _Pt2]] = []
    seen: set[tuple[_Pt2, _Pt2]] = set()
    for i in range(m):
        a, b = directed[i]
        for p, q in _split_edge(a, b, cuts[i]):
            if (p, q) in seen:
                continue
            seen.add((p, q))
            mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
            ex, ey = q[0] - p[0], q[1] - p[1]
            length = math.hypot(ex, ey)
            if length <= 0.0:
                continue
            # 進行方向 p→q の右向き法線 (ey, -ex)/length。外側にはみ出した点。
            rx = mx + _SLAB_SIDE_EPS * ey / length
            ry = my - _SLAB_SIDE_EPS * ex / length
            if not any(_point_in_poly(rx, ry, poly) for poly in oriented):
                boundary.append((p, q))

    return _chain_boundary(boundary)


def _next_boundary_edge(
    current: tuple[_Pt2, _Pt2], options: list[tuple[_Pt2, _Pt2]],
) -> tuple[_Pt2, _Pt2]:
    """境界追跡で分岐点に来たとき、内側を左に保つ次の辺(最も時計回り)を選ぶ。"""
    (px, py), (qx, qy) = current
    reverse = math.atan2(py - qy, px - qx)

    def clockwise(edge: tuple[_Pt2, _Pt2]) -> float:
        (ex1, ey1), (ex2, ey2) = edge
        d = math.atan2(ey2 - ey1, ex2 - ex1)
        a = (reverse - d) % (2.0 * math.pi)
        return a if a > 1e-9 else 2.0 * math.pi

    return min(options, key=clockwise)


def _simplify_ring(ring: list[_Pt2]) -> list[_Pt2]:
    """閉リング(末尾が先頭と重複)から共線の中間点を除いた頂点列を返す。"""
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    n = len(pts)
    out: list[_Pt2] = []
    for i in range(n):
        ax, ay = pts[(i - 1) % n]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > _SLAB_MERGE_TOL:
            out.append(pts[i])
    return out


def _chain_boundary(
    edges: list[tuple[_Pt2, _Pt2]],
) -> list[list[_Pt2]] | None:
    """有向境界辺をつないで閉ループのリストにする。開ループが生じたら None。"""
    from_map: dict[_Pt2, list[tuple[_Pt2, _Pt2]]] = {}
    for edge in edges:
        from_map.setdefault(edge[0], []).append(edge)
    remaining = set(edges)
    loops: list[list[_Pt2]] = []
    while remaining:
        start = min(remaining)
        cur = start
        ring: list[_Pt2] = [cur[0]]
        while True:
            remaining.discard(cur)
            ring.append(cur[1])
            if cur[1] == start[0]:
                break
            options = [e for e in from_map.get(cur[1], []) if e in remaining]
            if not options:
                return None
            cur = _next_boundary_edge(cur, options)
        simplified = _simplify_ring(ring)
        if len(simplified) >= 3:
            loops.append(simplified)
    return loops


def _collinear_overlap(a: _Pt2, b: _Pt2, c: _Pt2, d: _Pt2) -> float:
    """共線の線分 ab・cd の重なり長さを返す(共線でなければ 0)。"""
    ax, ay = a
    bx, by = b
    rx, ry = bx - ax, by - ay
    r_len = math.hypot(rx, ry)
    if r_len <= 0.0:
        return 0.0
    # cd が ab と平行かつ同一直線上か
    sx, sy = d[0] - c[0], d[1] - c[1]
    s_len = math.hypot(sx, sy)
    if s_len <= 0.0:
        return 0.0
    if abs(rx * sy - ry * sx) > _SLAB_ANGLE_TOL * r_len * s_len:
        return 0.0
    if abs((c[0] - ax) * ry - (c[1] - ay) * rx) > _SLAB_MERGE_TOL * r_len:
        return 0.0
    tc = ((c[0] - ax) * rx + (c[1] - ay) * ry) / (r_len * r_len)
    td = ((d[0] - ax) * rx + (d[1] - ay) * ry) / (r_len * r_len)
    lo, hi = max(0.0, min(tc, td)), min(1.0, max(tc, td))
    return (hi - lo) * r_len if hi > lo else 0.0


def _polys_connected(a: list[_Pt2], b: list[_Pt2]) -> bool:
    """底盤ポリゴン a・b が連続する(境界を共有 or 面で重なる)か。

    辺どうしが正の長さで共線オーバーラップする(辺を共有)か、辺が内部で交差する
    か、一方が他方の頂点を含む(面で重なる)とき連続とみなす。角(点)だけで
    接する場合は連続としない。
    """
    na, nb = len(a), len(b)
    for i in range(na):
        a1, a2 = a[i], a[(i + 1) % na]
        for j in range(nb):
            b1, b2 = b[j], b[(j + 1) % nb]
            if _collinear_overlap(a1, a2, b1, b2) > _SLAB_MERGE_TOL:
                return True
            # 内部で交差(端点を含まない真の交差)
            for pt in _seg_split_points(a1, a2, b1, b2):
                t = _param_on(a1, a2, pt)
                u = _param_on(b1, b2, pt)
                if _SLAB_ANGLE_TOL < t < 1.0 - _SLAB_ANGLE_TOL \
                        and _SLAB_ANGLE_TOL < u < 1.0 - _SLAB_ANGLE_TOL:
                    return True
    if any(_point_in_poly(x, y, b) for x, y in a):
        return True
    if any(_point_in_poly(x, y, a) for x, y in b):
        return True
    return False


def _param_on(a: _Pt2, b: _Pt2, p: _Pt2) -> float:
    """線分 a→b 上の点 p の正規化パラメータ(0=a, 1=b)を返す。"""
    rx, ry = b[0] - a[0], b[1] - a[1]
    length2 = rx * rx + ry * ry
    if length2 <= 0.0:
        return 0.0
    return ((p[0] - a[0]) * rx + (p[1] - a[1]) * ry) / length2


def _slab_components(polys: dict[int, list[_Pt2]]) -> list[list[int]]:
    """連続する(``_polys_connected``)底盤の連結成分をインデックス集合で返す。"""
    idxs = sorted(polys)
    parent = {i: i for i in idxs}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for p in range(len(idxs)):
        for q in range(p + 1, len(idxs)):
            if _polys_connected(polys[idxs[p]], polys[idxs[q]]):
                ra, rb = find(idxs[p]), find(idxs[q])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    comps: dict[int, list[int]] = {}
    for i in idxs:
        comps.setdefault(find(i), []).append(i)
    return [sorted(c) for _root, c in sorted(comps.items())]


def merge_slab_commands(slabs: list[SlabCommand]) -> list[SlabCommand]:
    """同じ厚さ・同じ高さで連続する底盤(基礎底盤系)を 1 枚に統合する。

    底盤(``thickness`` が非 None)を断面キー(``_slab_merge_key``＝レイヤ・クラス・
    コンクリート厚・高さ基準)ごとにグループ化し、各グループ内で連続する底盤の
    連結成分(``_slab_components``＝辺を共有 or 面で重なる連続底盤)を求め、成分ごとに
    多角形の和(``_polygon_union``。任意向きの単純多角形に対応するため、傾いた底盤や
    斜め辺=45 度取合いの底盤も統合できる)を 1 枚の底盤にする。統合できた成分の元命令は
    取り除き、統合スラブを成分の先頭位置に置く。単独の底盤・和が穴を含む/複数外形に
    分かれる成分・和の計算に失敗した成分(開ループ)はそのまま残す。地中梁
    (``thickness=None``)は統合しない。グループ化・成分処理とも入力順に対して決定的。
    """
    base_indices = [i for i, s in enumerate(slabs) if s['thickness'] is not None]
    groups: dict[tuple[object, ...], list[int]] = {}
    order: list[tuple[object, ...]] = []
    for i in base_indices:
        key = _slab_merge_key(slabs[i])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(i)

    dropped: set[int] = set()
    merged_at: dict[int, list[SlabCommand]] = {}
    for key in order:
        idxs = groups[key]
        polys = {i: _clean_ring(slabs[i]['boundary']) for i in idxs}
        polys = {i: p for i, p in polys.items() if len(p) >= 3}
        for comp in _slab_components(polys):
            if len(comp) < 2:
                continue
            loops = _polygon_union([polys[i] for i in comp])
            if loops is None:
                continue
            outer = [lp for lp in loops if _shoelace_signed(lp) > 0.0]
            holes = [lp for lp in loops if _shoelace_signed(lp) < 0.0]
            # 単一の外形・穴無しの成分だけ 1 枚に統合する(穴があると単一境界で
            # 表せず、部屋の下までコンクリートで埋めると誤りになるため見送る)。
            if len(outer) != 1 or holes:
                continue
            boundary = [[round(x, 6), round(y, 6)] for x, y in outer[0]]
            first = min(comp)
            base = slabs[first]
            merged: SlabCommand = {
                'layer': base['layer'],
                'class': base['class'],
                'boundary': boundary,
                'elevation': base['elevation'],
                'thickness': base['thickness'],
                'bound': base['bound'],
                'modifiers': [],
            }
            merged_at.setdefault(first, []).append(merged)
            dropped.update(comp)

    result: list[SlabCommand] = []
    for i, slab in enumerate(slabs):
        if i in merged_at:
            result.extend(merged_at[i])
        if i in dropped:
            continue
        result.append(slab)
    return result


def _wall_half_thickness_for_edge(
    a: _Pt2, b: _Pt2, walls: list[WallCommand],
) -> float:
    """底盤の辺 a→b に沿う立上りの半壁厚を返す(該当が無ければ 0)。

    辺と壁芯が平行・同一直線上で区間が重なる立上りを探し、最も重なりの大きい
    立上りの半壁厚を採る(底盤外形は立上りの壁心に一致するため、辺は壁芯上にある)。
    """
    ax, ay = a
    bx, by = b
    ex, ey = bx - ax, by - ay
    length = math.hypot(ex, ey)
    if length <= _SLAB_MERGE_TOL:
        return 0.0
    ux, uy = ex / length, ey / length
    best = 0.0
    best_overlap = _SLAB_MERGE_TOL
    for wall in walls:
        wx1, wy1 = wall['start']
        wx2, wy2 = wall['end']
        dx, dy = wx2 - wx1, wy2 - wy1
        wlen = math.hypot(dx, dy)
        if wlen <= _SLAB_MERGE_TOL:
            continue
        # 壁芯が辺と平行かつ同一直線上(端点の直交距離 ≈ 0)か
        if abs(ux * dy - uy * dx) / wlen > _SLAB_ANGLE_TOL:
            continue
        if abs(ux * (wy1 - ay) - uy * (wx1 - ax)) > _SLAB_MERGE_TOL:
            continue
        t1 = ux * (wx1 - ax) + uy * (wy1 - ay)
        t2 = ux * (wx2 - ax) + uy * (wy2 - ay)
        overlap = min(max(t1, t2), length) - max(min(t1, t2), 0.0)
        if overlap > best_overlap:
            best_overlap = overlap
            best = wall['thickness'] / 2.0
    return best


def _line_intersection(
    p1: _Pt2, d1: _Pt2, p2: _Pt2, d2: _Pt2,
) -> _Pt2 | None:
    """点 p・方向 d の 2 直線の交点を返す。平行なら None。"""
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-12:
        return None
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    t = (dx * d2[1] - dy * d2[0]) / denom
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def _offset_polygon(pts: list[_Pt2], dists: list[float]) -> list[_Pt2]:
    """CCW ポリゴンの各辺 i を外向きへ ``dists[i]`` だけ移動した頂点列を返す。

    各辺を外向き法線方向へ平行移動し、隣接する移動後の辺(直線)の交点を新しい
    頂点にする。凸角は外側へ伸び、凹角(入隅)は詰まる(可変量の外側オフセット)。
    """
    n = len(pts)
    lines: list[tuple[_Pt2, _Pt2]] = []
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        if length <= 0.0:
            lines.append(((ax, ay), (1.0, 0.0)))
            continue
        ux, uy = ex / length, ey / length
        nx, ny = uy, -ux  # CCW ポリゴンの外向き法線(進行方向の右)
        lines.append(((ax + dists[i] * nx, ay + dists[i] * ny), (ux, uy)))
    out: list[_Pt2] = []
    for i in range(n):
        q1, d1 = lines[(i - 1) % n]
        q2, d2 = lines[i]
        v = _line_intersection(q1, d1, q2, d2)
        if v is None:
            # 平行(同一直線の連続辺): 法線方向へずらした点で代用
            ax, ay = pts[i]
            ux, uy = d2
            v = (ax + dists[i] * uy, ay - dists[i] * ux)
        out.append(v)
    return out


def _offset_boundary_to_walls(
    boundary: list[list[float]], walls: list[WallCommand],
) -> list[list[float]] | None:
    """底盤外形の各辺を、沿っている立上りの外面まで外側へ広げた外形を返す。

    立上りに沿う辺が 1 つも無い(半壁厚 0 の辺だけ)なら None を返し、呼び出し側が
    元の外形をそのまま使う(立上りの無い独立基礎底盤等は動かさない)。CCW に正規化
    してから各辺の外側オフセット量(沿う立上りの半壁厚)を求め、``_offset_polygon``
    で外形を広げる。
    """
    pts: list[_Pt2] = [(x, y) for x, y in boundary]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    if _shoelace_signed(pts) < 0.0:
        pts = pts[::-1]
    n = len(pts)
    dists = [_wall_half_thickness_for_edge(pts[i], pts[(i + 1) % n], walls)
             for i in range(n)]
    if not any(d > 0.0 for d in dists):
        return None
    return [[round(x, 6), round(y, 6)] for x, y in _offset_polygon(pts, dists)]


def align_slabs_to_wall_faces(
    slabs: list[SlabCommand], walls: list[WallCommand],
) -> list[SlabCommand]:
    """底盤(基礎底盤系)の外周を立上りの外面に合わせて外側へ広げる。

    ホームズ君 IFC の底盤外形は立上り(基礎梁)の**壁心**に一致しているため、
    各底盤の外周辺のうち立上りに沿う辺を、その立上りの**外面**(壁心 + 半壁厚)まで
    外側へ広げる。立上りに沿わない辺は動かさない(``_offset_boundary_to_walls``)。
    地中梁(``thickness=None``)は対象外でそのまま残す。``walls`` が空なら無変更。
    """
    if not walls:
        return slabs
    result: list[SlabCommand] = []
    for slab in slabs:
        if slab['thickness'] is None:
            result.append(slab)
            continue
        boundary = _offset_boundary_to_walls(slab['boundary'], walls)
        if boundary is None:
            result.append(slab)
            continue
        result.append({
            'layer': slab['layer'],
            'class': slab['class'],
            'boundary': boundary,
            'elevation': slab['elevation'],
            'thickness': slab['thickness'],
            'bound': slab['bound'],
            'modifiers': slab.get('modifiers', []),
        })
    return result
