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

from ..document import MemberCommand, RafterCommand
from .footing import _add, _scale, _world_solid
from .grid import resolve_lines
from .story import LEVEL_TARUKI, layer_prefix_for, resolve_beam_top_offset
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

# 支持部分の差し込み(``embedment``)に使う桁幅を、受ける軒桁(横架材命令)から
# 相互参照できなかったときのフォールバック値 (mm)。差し込みはこの半分になる。
DEFAULT_GIRDER_WIDTH = 105.0
# 支持点の真下に軒桁の芯線が見つかるとみなす直交距離の許容 (mm)。屋根面が横架材
# 天端 Z と交わる支持点は受ける軒桁の天端(=芯線)のほぼ真上に来るため、この許容
# 内で最も近い横架材の幅を桁幅として採る。
_GIRDER_SEARCH_TOL = 100.0
# 桁幅参照で支持点が軒桁の芯線区間内にあるとみなす軸方向の余裕 (mm)。
_GIRDER_ALONG_TOL = 1.0
# 桁幅参照で「軒桁は垂木に直交する」ことを使い、垂木と平行に走る材(継ぎ手・側並び)を
# 除くための sin(なす角) の下限。これ未満(ほぼ平行)の材は軒桁とみなさない。
_GIRDER_PERP_SIN = 0.1

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


def _girder_width_at(
    px: float,
    py: float,
    rdx: float,
    rdy: float,
    members: list[MemberCommand],
) -> float:
    """支持点 (px, py) の真下にある軒桁(横架材命令)の幅を返す。

    支持点は屋根面(垂木下端)が横架材天端 Z と交わる点で、受ける軒桁の天端
    (=芯線)のほぼ真上に来る。``members`` のうち芯線が支持点に最も近い(直交距離
    ``_GIRDER_SEARCH_TOL`` 以内・射影が芯線区間内)ものの幅を桁幅として採り、見つから
    なければ既定値 ``DEFAULT_GIRDER_WIDTH`` を返す。座標系は member 命令と同じグリッド
    中心オフセット済み。``rdx``/``rdy`` は垂木の方向(支持点→棟)で、垂木と平行に走る材
    (継ぎ手・側並び)を除いて軒桁(垂木に直交)を選ぶために使う。判定は ``members`` の
    並び順に依存しない決定的な結果になる。
    """
    rlen = math.hypot(rdx, rdy)
    best_dist = _GIRDER_SEARCH_TOL
    best_width: float | None = None
    for m in members:
        sx, sy = m['start']
        ex, ey = m['end']
        mdx, mdy = ex - sx, ey - sy
        mlen = math.hypot(mdx, mdy)
        if mlen <= 0.0:
            continue
        ux, uy = mdx / mlen, mdy / mlen
        # 芯線に沿う射影位置 t が区間内か、芯線からの直交距離が許容内かを判定する。
        t = (px - sx) * ux + (py - sy) * uy
        if t < -_GIRDER_ALONG_TOL or t > mlen + _GIRDER_ALONG_TOL:
            continue
        perp = abs(-(px - sx) * uy + (py - sy) * ux)
        if perp > best_dist:
            continue
        # 垂木と平行に走る材は軒桁でないため除外する(なす角の sin が小さい)。
        if rlen > 0.0 and abs(rdx * uy - rdy * ux) / rlen < _GIRDER_PERP_SIN:
            continue
        best_dist = perp
        best_width = m['width']
    return best_width if best_width is not None else DEFAULT_GIRDER_WIDTH


def _rafters_for_plane(
    verts: list[_Vec3],
    normal: _Vec3,
    layer: str,
    storey_elevation: float,
    center_x: float,
    center_y: float,
    beam_top_z: float | None = None,
    story_members: list[MemberCommand] | None = None,
) -> list[RafterCommand]:
    """1 つの屋根面(平面外形頂点列 + 単位法線)から垂木命令のリストを組み立てる。

    最急勾配方向(法線の水平成分)へ垂木を流し、それに直交する掃引方向へ掃引線を
    並べ、各掃引線を外形でクリップした区間を 1 本ずつ命令にする。掃引位置は
    **屋根面の両端の垂木を端から垂木幅の半分だけ内側**へ寄せ(端に軸を合わせると
    垂木幅の半分がはみ出すため)、内部は ``RAFTER_INTERVAL``(455mm)**以下**で
    割り付ける(中間は 455mm ちょうど・端数は両端の 2 区間へ等分。``_sweep_positions``)。

    **start=軒側(支持点)・end=棟側(高い端)**。支持点は屋根面(垂木下端)が
    横架材天端(最上階は軒高)の Z レベル ``beam_top_z`` と交わる点(=軒桁の中心線
    ＝横架材高さとの交点)で、``elevation`` はその ``beam_top_z``。``embedment``
    (支持部分の差し込み)は支持点の真下にある軒桁(``story_members``)の桁幅の半分
    (``_girder_width_at``)で、支持点→壁外面の水平距離を表す。``overhang``(壁外面から
    軒先の距離)は支持点→軒先の水平距離から ``embedment`` を引いた残り。VW の垂木は
    軒先を 支持点 + 差し込み + 軒の出 の位置に置くため、両者の和が支持点→軒先に
    なるようにする。``beam_top_z`` が None、または屋根面の下端(軒先)が既に
    ``beam_top_z`` 以上で支持点が取れない場合は start=軒先のまま overhang=0 にする。
    ``label`` は
    垂木の仕様ラベル(``45×45@455``)。天端 Z はストーリ Elevation を足した絶対値。
    ほぼ水平な面・広がりが極小の面は空リスト。区間の平面投影長が極小(隅木際の極小片・
    端で退化した面等)のものは ``_MIN_RAFTER_LENGTH`` 未満として配置しない。
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
    members = story_members or []
    # 仕様ラベル(全垂木で共通。断面・間隔が決め打ちのため)。
    w = int(round(DEFAULT_RAFTER_WIDTH))
    h = int(round(DEFAULT_RAFTER_HEIGHT))
    label = f'{w}×{h}@{int(round(RAFTER_INTERVAL))}'
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
            _d_lo, lx_, ly_ = hits[j + 1]  # d 最大 = 低い側 = 軒先
            length = math.hypot(lx_ - hx, ly_ - hy)
            if length < _MIN_RAFTER_LENGTH:
                continue
            z_tip = z_at(lx_, ly_)      # 軒先の天端 Z
            z_ridge = z_at(hx, hy)      # 棟側の天端 Z
            # 支持点 = 屋根面が横架材天端(軒高)Z と交わる点。軒先→棟の線上で
            # z=beam_top_z となる位置 s。軒先が既に beam_top_z 以上(s<=0)や
            # 面全体が下(s>=1)なら支持点は取れないので軒先のままにする。
            sx, sy, support_z, support_to_tip = lx_, ly_, z_tip, 0.0
            if beam_top_z is not None:
                dz = z_ridge - z_tip
                s = (beam_top_z - z_tip) / dz if dz > _FLAT_TOL else 0.0
                if 0.0 < s < 1.0:
                    sx = lx_ + s * (hx - lx_)
                    sy = ly_ + s * (hy - ly_)
                    support_z = beam_top_z
                    support_to_tip = math.hypot(sx - lx_, sy - ly_)
            csx, csy = sx - center_x, sy - center_y
            chx, chy = hx - center_x, hy - center_y
            embedment = _girder_width_at(
                csx, csy, chx - csx, chy - csy, members) / 2.0
            # 壁外面から軒先の距離(overhang)= 支持点→軒先(support_to_tip)から
            # 支持部分の差し込み(embedment = 支持点→壁外面の水平距離)を引いた残り。
            # VW の垂木は軒先を 支持点 + 差し込み(bearinginset) + 軒の出(overhang) の
            # 位置に置く(実オブジェクトで確認)ため、両者の和が support_to_tip に
            # なるよう軒の出から差し込みぶんを引き、軒先が支持点→軒先の位置に揃うようにする。
            overhang = max(0.0, support_to_tip - embedment)
            commands.append({
                'layer': layer,
                'class': CLASS_TARUKI,
                'width': DEFAULT_RAFTER_WIDTH,
                'height': DEFAULT_RAFTER_HEIGHT,
                # start=軒側(支持点)、end=棟側(高い端)
                'start': [csx, csy],
                'end': [chx, chy],
                'elevation': support_z,
                'end_elevation': z_ridge,
                'overhang': overhang,
                'embedment': embedment,
                'label': label,
            })
    return commands


def build_rafter_commands(
    ifc_file: ifcopenshell.file,
    members: list[MemberCommand] | None = None,
) -> list[RafterCommand]:
    """IFC の屋根版から垂木命令のリストを組み立てる。

    FL ストーリ(名前が FL で終わる IfcBuildingStorey)を Elevation 昇順に走査し、
    各ストーリに含まれる ``屋根版`` の IfcSlab から垂木を導出する。配置先レイヤは
    そのストーリの ``n-垂木``(母屋レイヤの直上、``story.py`` が生成)。ストーリの
    ローカル配置 Z(=Elevation)を足して天端を絶対 Z にする。

    支持点(start)は屋根面が横架材天端(最上階は軒高)の Z レベルと交わる点にする
    ため、各階の横架材天端 Z(``elevation + resolve_beam_top_offset``、最上階は軒高
    ＝ ``elevation``)を求めて ``_rafters_for_plane`` に渡す。差し込み(``embedment``)に
    使う桁幅は受ける軒桁(横架材命令)から相互参照するため、``members``(横架材命令。
    未指定なら内部で ``build_member_commands`` を組み立てる)を階ごとにレイヤ接頭辞で
    絞って渡す。ストーリが無ければ空リスト。走査順(ストーリ→含有要素)に対して決定的。
    """
    if members is None:
        from .member import build_member_commands
        members = build_member_commands(ifc_file)

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
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        layer = f'{prefix}-{LEVEL_TARUKI}'
        elevation = float(storey.Elevation or 0.0)
        # 支持点が乗る横架材天端の絶対 Z(最上階は軒高＝offset 0)。
        if is_top:
            beam_top_z = elevation
        else:
            beam_top_z = elevation + resolve_beam_top_offset(storey)
        # 桁幅参照用に同じ階(同じレイヤ接頭辞)の横架材だけを渡す。
        story_members = [m for m in members if m['layer'].startswith(f'{prefix}-')]
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
                    verts, normal, layer, elevation, center_x, center_y,
                    beam_top_z, story_members))
    return commands
