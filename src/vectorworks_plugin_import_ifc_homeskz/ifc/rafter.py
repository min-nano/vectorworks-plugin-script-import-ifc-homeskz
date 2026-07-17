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
- **配置間隔**: 勾配方向に直交する方向(軒・棟に平行)へ掃引し、各掃引線を屋根面の
  外形でクリップした区間を 1 本の垂木にする。**屋根面の両端(ケラバ側)の垂木は
  屋根面の端から垂木幅の半分だけ内側**に置く(垂木は掃引位置を断面中央にして描かれ、
  端に軸を合わせると垂木幅の半分が屋根面からはみ出すため)。内部は ``RAFTER_INTERVAL``
  (=455mm、要件の決め打ち)**以下**で割り付ける(中間は 455mm ちょうど・端数＝余りは
  両端の 2 区間へ等分)。
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
# 掃引線と外形辺の交点判定の許容 (mm)。屋根の両端の掃引線は外形の頂点に接して
# 退化する(特に走査線法の半開区間判定 ``<=0<`` は上端 e_max で交点 0 になる)ため、
# 両端の掃引線はこの分だけ内側へ寄せて確実に区間を得る。
_EDGE_TOL = 1.0

_Vec3 = tuple[float, float, float]


def _sweep_positions(
    e_min: float, e_max: float, interval: float, inset: float
) -> list[float]:
    """屋根面の e 方向(軒・棟に平行)の広がり ``[e_min, e_max]`` に垂木の掃引位置を
    割り付ける。

    要件:

    - **両端の垂木は屋根面の端から ``inset``(=垂木幅の半分)だけ内側**に置く(垂木は
      掃引位置を軸=断面中央にして描かれるため、端に軸を合わせると垂木幅の半分が屋根面
      から外へはみ出す。軸を半幅内側へ寄せると端の垂木の外面が屋根面の端に揃う)。
    - 内部は間隔が ``interval``(=455mm)**以下**になるように分割する。
    - **中間は常に ``interval`` ちょうど**、**端数(余り)は両端の 2 区間へ等分**して
      寄せる(両端の区間は ``interval`` 以下)。

    両端を半幅内側へ寄せた実効範囲 ``[e_min+inset, e_max-inset]``(幅
    ``W = e_max - e_min - 2*inset``)を ``interval`` 以下に分割する最小の区間数
    ``n = ceil(W / interval)`` を採り、中間 ``n-2`` 区間を ``interval`` ちょうど、
    残り ``W - (n-2)*interval`` を両端 2 区間へ等分する。``W`` が ``interval`` の
    整数倍なら全区間が ``interval``。半幅内側へ寄せることで両端の掃引線は外形頂点に
    接して退化せず(走査線法の半開判定が上端で交点を落とす問題も回避)、確実に区間を
    得られる。
    """
    lo_edge, hi_edge = e_min + inset, e_max - inset
    width = hi_edge - lo_edge
    if width <= 2.0 * _EDGE_TOL:
        # 半幅を差し引くと広がりが極小(屋根が垂木幅程度に狭い): 中央 1 本のみ。
        return [(e_min + e_max) / 2.0]
    n = int(math.ceil(width / interval - 1e-9))
    if n <= 1:
        raw = [lo_edge, hi_edge]
    else:
        end_gap = (width - (n - 2) * interval) / 2.0
        raw = [lo_edge, lo_edge + end_gap]
        raw.extend(lo_edge + end_gap + i * interval for i in range(1, n - 1))
        raw.append(hi_edge)
    return raw


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

    最急勾配方向(法線の水平成分)へ垂木を流し、それに直交する掃引方向へ掃引線を
    並べ、各掃引線を外形でクリップした区間を 1 本ずつ命令にする。掃引位置は
    **屋根面の両端(e_min・e_max＝ケラバ側)には必ず 1 本ずつ**置き、内部は
    ``RAFTER_INTERVAL``(455mm)**以下**で割り付ける(中間は 455mm ちょうど・端数は
    両端の 2 区間へ等分。``_sweep_positions``)。start=軒側(低い端)・end=棟側
    (高い端)、天端 Z はストーリ Elevation を足した絶対値。ほぼ水平な面・広がりが
    極小の面は空リスト。区間の平面投影長が極小(隅木際の極小片・端で退化した面等)の
    ものは ``_MIN_RAFTER_LENGTH`` 未満として配置しない。
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
    # 面の e 方向の広がり [e_min, e_max] の**両端の垂木は屋根面の端から垂木幅の
    # 半分だけ内側**へ寄せ(端に軸を合わせると垂木幅の半分がはみ出すため)、内部は
    # ``RAFTER_INTERVAL``(455mm)**以下**で割り付ける(中間は 455mm ちょうど・
    # 端数は両端の 2 区間へ等分。``_sweep_positions``)。範囲外・端ちょうどで区間の
    # 取れない掃引線は走査線が空になり自然に除外される。
    n = len(plan)
    commands: list[RafterCommand] = []
    for t in _sweep_positions(
            e_min, e_max, RAFTER_INTERVAL, DEFAULT_RAFTER_WIDTH / 2.0):
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
