"""野地板 (屋根版から導出) の解析と roof 命令の組み立て。vs 非依存。

野地板(屋根の下地合板)は屋根版(``IfcSlab`` の屋根面。``Name`` が ``屋根版`` 始まり)
1 面ごとに、その勾配・外形から VectorWorks の**屋根ツール(``vs.BeginRoof``)**で
単勾配の屋根オブジェクトとして作図する。要件により**厚みは 12mm 固定**(IFC に
情報が無ければ 12mm。``NOJIITA_THICKNESS`` に集約)。

屋根面のジオメトリ(平面外形頂点列 + 単位法線)は垂木(``ifc/rafter.py``)と同じ
``_roof_plane`` を再利用する(いずれも屋根版から屋根面を取り出す)。屋根面の法線から
最急勾配方向 ``d``(軒→棟の逆向き)・軒に平行な方向 ``e`` を求め、以下を組み立てる。

- **軒(屋根軸)**: 屋根面の最も低い辺の位置に軸を置く。屋根オブジェクトはこの軸から
  棟側(upslope)へ勾配なりに立ち上がる。軸は footprint を ``d`` 方向へ射影した最下点
  (最も軒側)を通り、``e`` 方向に footprint の広がりぶん伸ばした線分にする(footprint
  全体が軸の棟側=upslope 側に来るようにする)。
- **勾配**: 屋根面の単位法線の水平成分 ``dh`` と鉛直成分 ``nz`` から
  ``rise=dh``・``run=nz``(slope=rise/run=tanθ)。
- **高さ**: 軸(軒)の天端 Z の絶対値を ``elevation`` に持たせる。``BeginRoof`` は軸を
  Z=0 で作るため、描画フェーズが作成後 ``Move3D`` で軒の高さへ移動する。

座標は通り芯・垂木と同じグリッド中心オフセットで補正する。配置先レイヤは屋根版を
含むストーリの垂木レイヤの直上に独立させた ``n-野地板``(``story.py`` が生成)。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import RoofCommand
from .grid import resolve_lines
from .rafter import _ROOF_SLAB_PREFIX, _roof_plane
from .story import LEVEL_NOJIITA, layer_prefix_for
from .structural_class import CLASS_ROOF_SHEATHING

if TYPE_CHECKING:
    import ifcopenshell

# 野地板の厚み (mm)。要件により 12mm 固定(IFC に情報が無ければ 12mm)。
NOJIITA_THICKNESS = 12.0

# 屋根面の法線の水平成分がこれ以下(ほぼ水平な面)なら勾配方向・軒が定まらないため
# 屋根オブジェクトを作らない(垂木と同じ扱い)。
_FLAT_TOL = 1e-6
# footprint の広がり(軒方向・勾配方向)がこれ未満なら退化とみなしスキップ (mm)。
_MIN_SPAN = 1.0

_Vec3 = tuple[float, float, float]


def _roof_command_for_plane(
    verts: list[_Vec3],
    normal: _Vec3,
    layer: str,
    storey_elevation: float,
    center_x: float,
    center_y: float,
) -> RoofCommand | None:
    """1 つの屋根面(平面外形頂点列 + 単位法線)から roof 命令を組み立てる。

    最も低い辺(軒)に沿う屋根軸・棟側の upslope 定義点・勾配(rise/run)・軒の天端 Z
    を求める。ほぼ水平な面・広がりが極小の面は None(屋根オブジェクトを作らない)。
    """
    nx, ny, nz = normal
    dh = math.hypot(nx, ny)
    if dh <= _FLAT_TOL:
        return None
    # 勾配方向 d(最急降下=水平法線方向)。+d へ進むと天端 Z は下がる(軒側)。
    dx, dy = nx / dh, ny / dh
    # 軒・棟に平行な方向 e(勾配方向に直交)。
    ex, ey = -dy, dx
    # 棟(高い)側を指す upslope 単位方向(勾配方向の逆)。
    ux, uy = -dx, -dy

    plan = [(v[0], v[1]) for v in verts]
    px0, py0, pz0 = verts[0]

    def z_at(x: float, y: float) -> float:
        # 屋根面(平面)上の点の天端 Z(絶対値。ストーリ相対 + Elevation)。
        return pz0 - (nx * (x - px0) + ny * (y - py0)) / nz + storey_elevation

    ds = [x * dx + y * dy for x, y in plan]
    es = [x * ex + y * ey for x, y in plan]
    d_min, d_max = min(ds), max(ds)
    e_min, e_max = min(es), max(es)
    e_span = e_max - e_min
    d_span = d_max - d_min
    if e_span < _MIN_SPAN or d_span < _MIN_SPAN:
        return None

    # 軒(屋根軸)の基準点 = 最も低い(最も +d 側=軒側)の頂点。ここを通り e 方向に
    # 伸ばした軸なら footprint 全体が軸の棟側(upslope 側)に来る。
    eave_idx = max(range(len(plan)), key=lambda i: ds[i])
    ax, ay = plan[eave_idx]
    # 軸は軒に沿って footprint の広がりぶん伸ばす(方向が主で、長さは表現用)。
    p1 = (ax, ay)
    p2 = (ax + ex * e_span, ay + ey * e_span)
    # upslope 定義点は軸から棟側へ勾配方向の広がりぶん進んだ点(方向が主)。
    up = (ax + ux * d_span, ay + uy * d_span)
    elevation = z_at(ax, ay)

    return {
        'layer': layer,
        'class': CLASS_ROOF_SHEATHING,
        'boundary': [[x - center_x, y - center_y] for x, y in plan],
        'axis_start': [p1[0] - center_x, p1[1] - center_y],
        'axis_end': [p2[0] - center_x, p2[1] - center_y],
        'upslope': [up[0] - center_x, up[1] - center_y],
        'rise': dh,
        'run': nz,
        'thickness': NOJIITA_THICKNESS,
        'elevation': elevation,
    }


def build_roof_commands(ifc_file: ifcopenshell.file) -> list[RoofCommand]:
    """IFC の屋根版から野地板(roof)命令のリストを組み立てる。

    FL ストーリ(名前が ``FL`` で終わる ``IfcBuildingStorey``)を Elevation 昇順に
    走査し、各ストーリに含まれる ``屋根版`` の ``IfcSlab`` 1 面ごとに屋根オブジェクトの
    roof 命令を組み立てる。配置先レイヤはそのストーリの ``n-野地板``(垂木レイヤの
    直上、``story.py`` が生成)。ストーリのローカル配置 Z(=Elevation)を足して軒の
    天端を絶対 Z にする。ストーリが無ければ空リスト。走査順(ストーリ→含有要素)に
    対して決定的。
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

    commands: list[RoofCommand] = []
    for i, storey in enumerate(storeys):
        prefix = layer_prefix_for(i, i == top_idx)
        layer = f'{prefix}-{LEVEL_NOJIITA}'
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
                command = _roof_command_for_plane(
                    verts, normal, layer, elevation, center_x, center_y)
                if command is not None:
                    commands.append(command)
    return commands
