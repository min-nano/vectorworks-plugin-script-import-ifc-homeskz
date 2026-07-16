"""垂木 (屋根版から導出) の解析と rafter 命令の組み立て。vs 非依存。

ホームズ君 IFC には垂木が一切出力されない(オブジェクト・型・プロパティのいずれ
にも垂木の位置や仕様が現れない)。そのため垂木は IFC から直接抽出できず、要件
どおり **屋根版(IfcSlab の屋根面)の勾配・外形から導出** する。屋根の各面は
``屋根版:{連番}`` の IfcSlab として、勾配した平面外形を鉛直に押し出したソリッドで
表現される(押し出し=屋根の厚み)。この平面外形と面の法線から屋根面の勾配・向きを
求め、以下の手順で垂木を流す。

- **勾配方向(垂木の流れ方向)**: 屋根面の法線の水平成分 = 最急勾配方向(母屋・
  棟木・軒桁に直交する方向)。垂木はこの方向に沿って軒側(低い端)から棟側(高い端)
  へ架かる。
- **配置間隔**: 勾配方向に直交する方向(軒・棟に平行)へ ``RAFTER_INTERVAL``
  (=455mm、要件の決め打ち)間隔で掃引し、各掃引線を屋根面の外形でクリップした
  区間を 1 本の垂木にする。面の広がりに 455 グリッドを中央寄せに割り付ける。
- **断面**: IFC に垂木の寸法情報が無いため既定 45×45(要件の決め打ち)。
- **配置先レイヤ**: 屋根版を含むストーリの母屋レイヤの直上に独立させた 垂木 レイヤ
  (``n-垂木``)。最上階(屋根)の主屋根だけでなく、中間階に架かる下屋根(下屋)の
  屋根版も同様に、その階の ``n-垂木`` に配置する(母屋の分離と同じ扱い)。

座標は通り芯・横架材と同じグリッド中心オフセットで補正する。屋根版のソリッドは
基礎・火打と同じ ``footing._world_solid`` でワールド情報に変換する(押し出し方向の
プロファイル頂点をワールド化)。ストーリのローカル配置は XY=0・Z=Elevation なので、
平面座標はそのまま(中心オフセットのみ)・天端 Z はストーリ Elevation を足して
絶対値にする(横架材の ``storey_elevation + oz`` と同じ規約)。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import RafterCommand
from .footing import _add, _scale, _world_solid
from .grid import resolve_lines
from .story import LEVEL_TARUKI, layer_prefix_for
from .structural_class import CLASS_TARUKI

if TYPE_CHECKING:
    import ifcopenshell

# 屋根面を表す IfcSlab の Name 接頭辞
_ROOF_SLAB_PREFIX = '屋根版'

# 垂木の既定断面 (mm)。IFC に垂木の寸法情報が無いため決め打ち(要件どおり 45×45)。
DEFAULT_RAFTER_WIDTH = 45.0
DEFAULT_RAFTER_HEIGHT = 45.0
# 垂木の配置間隔 (mm)。IFC に情報が無いため決め打ち(要件どおり @455)。
RAFTER_INTERVAL = 455.0

# 屋根面の法線の水平成分がこれ以下(ほぼ水平な面)なら勾配方向が定まらないため
# 垂木を流さない
_FLAT_TOL = 1e-6
# クリップした垂木の平面投影長がこれ未満(隅木際の極小片等)なら配置しない (mm)
_MIN_RAFTER_LENGTH = 100.0
# 掃引線と外形辺の交点判定の許容 (mm)
_EDGE_TOL = 1.0

_Vec3 = tuple[float, float, float]


def _roof_plane(
    element: ifcopenshell.entity_instance,
) -> tuple[list[_Vec3], _Vec3] | None:
    """屋根版の IfcSlab からワールド座標の平面外形頂点列と単位法線を返す。

    ``footing._world_solid`` が返す配置(原点・軸)とプロファイル頂点(ローカル XY、
    z=0)からワールド頂点 ``origin + lx*u + ly*v`` を組み立てる。法線は配置の局所
    Z 軸(``lz``)で、上向き(z 成分 > 0)に揃える。頂点が 3 点未満・ソリッドが
    取得できない場合は None。座標はストーリのローカル配置基準(XY は絶対、Z は
    ストーリ相対)。
    """
    solid = _world_solid(element)
    if solid is None:
        return None
    (origin, lx, ly, lz), _extrude, _depth, pts, _dims = solid
    if len(pts) < 3:
        return None
    verts = [_add(origin, _add(_scale(lx, u), _scale(ly, v))) for u, v in pts]
    normal = lz
    if normal[2] < 0.0:
        # 上向き法線に揃える(平面式・勾配方向はこの符号反転に対して不変)。
        normal = (-normal[0], -normal[1], -normal[2])
    return verts, normal


def _rafters_for_plane(
    verts: list[_Vec3],
    normal: _Vec3,
    layer: str,
    storey_elevation: float,
    center_x: float,
    center_y: float,
) -> list[RafterCommand]:
    """1 つの屋根面(平面外形頂点列 + 単位法線)から垂木命令のリストを組み立てる。

    最急勾配方向(法線の水平成分)へ垂木を流し、それに直交する方向へ
    ``RAFTER_INTERVAL`` 間隔で掃引した線を外形でクリップした区間を 1 本ずつ
    命令にする。start=軒側(低い端)・end=棟側(高い端)、天端 Z はストーリ
    Elevation を足した絶対値。ほぼ水平な面・広がりが極小の面は空リスト。
    """
    nx, ny, nz = normal
    dh = math.hypot(nx, ny)
    if dh <= _FLAT_TOL:
        return []
    # 勾配方向 d(最急降下=水平法線方向)。+d へ進むと天端 Z は下がる(軒側)。
    dx, dy = nx / dh, ny / dh
    # 掃引方向 e(軒・棟に平行。勾配方向に直交)。
    ex, ey = -dy, dx

    plan = [(v[0], v[1]) for v in verts]
    px0, py0, pz0 = verts[0]

    def z_at(x: float, y: float) -> float:
        # 屋根面(平面)上の点の天端 Z。ストーリ相対 → Elevation を足して絶対値に。
        # 法線の符号反転に対して不変(nx/ny/nz が揃って反転し比が変わらない)。
        return pz0 - (nx * (x - px0) + ny * (y - py0)) / nz + storey_elevation

    es = [x * ex + y * ey for x, y in plan]
    e_min, e_max = min(es), max(es)
    span = e_max - e_min
    if span < _MIN_RAFTER_LENGTH:
        return []
    # 面の e 方向の広がりの中央に 1 本を置き、両側へ ``RAFTER_INTERVAL``(455mm)
    # 間隔で流す(決定的・左右対称。間隔はきっちり 455mm を保ち、両端の垂木は
    # 軒・棟の端から 455mm 以内に入る)。範囲外・端ちょうどの掃引線は走査線が
    # 空になり自然に除外される。
    center_e = (e_min + e_max) / 2.0
    half = int(math.floor((span / 2.0) / RAFTER_INTERVAL)) + 1

    n = len(plan)
    commands: list[RafterCommand] = []
    for k in range(-half, half + 1):
        t = center_e + k * RAFTER_INTERVAL
        if t <= e_min + _EDGE_TOL or t >= e_max - _EDGE_TOL:
            continue
        # 掃引線 { p : p·e = t } と外形の交点を集め、勾配方向 d の座標を添える。
        hits: list[tuple[float, float, float]] = []
        for i in range(n):
            x0, y0 = plan[i]
            x1, y1 = plan[(i + 1) % n]
            f0 = x0 * ex + y0 * ey - t
            f1 = x1 * ex + y1 * ey - t
            if (f0 <= 0.0 < f1) or (f1 <= 0.0 < f0):
                r = f0 / (f0 - f1)
                ix = x0 + r * (x1 - x0)
                iy = y0 + r * (y1 - y0)
                hits.append((ix * dx + iy * dy, ix, iy))
        if len(hits) < 2:
            continue
        # d 昇順に並べ、[偶, 奇] の区間が面内(非凸面も走査線法で正しく分割される)。
        hits.sort()
        for j in range(0, len(hits) - 1, 2):
            _d_hi, hx, hy = hits[j]        # d 最小 = 高い側 = 棟側
            _d_lo, lx_, ly_ = hits[j + 1]  # d 最大 = 低い側 = 軒側
            length = math.hypot(lx_ - hx, ly_ - hy)
            if length < _MIN_RAFTER_LENGTH:
                continue
            commands.append({
                'layer': layer,
                'class': CLASS_TARUKI,
                'width': DEFAULT_RAFTER_WIDTH,
                'height': DEFAULT_RAFTER_HEIGHT,
                # start=軒側(低い端)、end=棟側(高い端)
                'start': [lx_ - center_x, ly_ - center_y],
                'end': [hx - center_x, hy - center_y],
                'elevation': z_at(lx_, ly_),
                'end_elevation': z_at(hx, hy),
            })
    return commands


def build_rafter_commands(ifc_file: ifcopenshell.file) -> list[RafterCommand]:
    """IFC の屋根版から垂木命令のリストを組み立てる。

    FL ストーリ(名前が FL で終わる IfcBuildingStorey)を Elevation 昇順に走査し、
    各ストーリに含まれる ``屋根版`` の IfcSlab から垂木を導出する。配置先レイヤは
    そのストーリの ``n-垂木``(母屋レイヤの直上、``story.py`` が生成)。ストーリの
    ローカル配置 Z(=Elevation)を足して天端を絶対 Z にする。ストーリが無ければ
    空リスト。走査順(ストーリ→含有要素)に対して決定的。
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

    commands: list[RafterCommand] = []
    for i, storey in enumerate(storeys):
        prefix = layer_prefix_for(i, i == top_idx)
        layer = f'{prefix}-{LEVEL_TARUKI}'
        elevation = float(storey.Elevation or 0.0)
        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not element.is_a('IfcSlab'):
                    continue
                if not (element.Name or '').startswith(_ROOF_SLAB_PREFIX):
                    continue
                plane = _roof_plane(element)
                if plane is None:
                    continue
                verts, normal = plane
                commands.extend(_rafters_for_plane(
                    verts, normal, layer, elevation, center_x, center_y))
    return commands
