"""横架材 (IfcBeam / IfcMember) の解析と member 命令の組み立て。vs 非依存。

IFC の IfcBeam / IfcMember を走査し、各階の横架材天端レイヤ
(最上階は軒高レイヤ)に配置する member 命令を生成する。
構造材 ID は断面寸法と材種から "{幅}×{背} - {材種}" の形式で自動生成する。

ホームズ君 IFC の梁は断面中心線(プロファイル中心の押し出し軸)で配置される。
一方 VW 構造材ツールの断面基準点は左右中央・上端(天端中央)なので、
断面中心線を軸直交方向に背/2 だけ持ち上げた天端中央線を命令に格納する。
Axis 属性に Z 成分を持つ梁(隅木等の傾斜梁)は始端と終端の
天端 Z(``elevation``/``end_elevation``)が異なる傾斜した命令になる。

登り梁は矩形断面ではなく、材の側面(長さ×せいの平行四辺形。端部の直切り=鉛直面)を
厚み方向へ押し出した任意断面(``IfcArbitraryClosedProfileDef``)で表される。矩形断面を
前提とする ``_get_profile_dims`` では拾えず取りこぼされるため、
``_sloped_member_geometry`` で平行四辺形の 4 頂点から中心軸・断面・傾斜を導出し、
母屋・棟木と同じスキームで専用レイヤ(``n-登り梁``)に分離して配置する。

登り梁の端部は直切り(鉛直面)なので、天端中央線の端点は断面中心軸(鉛直な端面の
中央高さを通る)の**直上**(XY は同じ)= 鉛直な端面の上端に取り、高さは
断面中心 + せい/(2·cosθ) にする。矩形前提の軸直交持ち上げ(通常の横架材・軸直交切りの
傾斜梁)を登り梁に使うと、天端が (せい/2)(secθ − cosθ) 低くなって垂木下面(屋根勾配)に
届かず、端部も勾配ぶん(せい/2·sinθ)軒側へずれて受ける柱との間に隙間ができるため、
直切りの幾何(XY ずらし無し・鉛直持ち上げ)で天端を垂木下面に合わせ端部を柱に密着させる。

横架材同士が食い込んでいる箇所(甲乙梁の T 字や出隅の L 字の取り合い等)は、
相互の食い込み量を比べて勝ち負けを判定し、負け側(深く食い込む側)の端部を
相手梁の面まで詰めて干渉を解消する(``resolve_member_interferences``)。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import MemberCommand, StoryBoundCommand
from .footing import _add, _scale, _world_solid
from .grid import resolve_lines
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    LEVEL_MOYA,
    LEVEL_NOBORIBARI,
    layer_prefix_for,
    resolve_beam_top_offset,
)
from .structural_class import (
    CLASS_MOYA,
    CLASS_MUNAGI,
    CLASS_NOBORIBARI,
    resolve_member_class,
)

if TYPE_CHECKING:
    import ifcopenshell

_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')

# 横架材同士の食い込み(T 字・L 字の取り合い)を解消する際の許容値 (mm)
_Z_OVERLAP_TOL = 1.0    # この値以下の Z 重なりは干渉とみなさない(段差梁は対象外)
_PARALLEL_TOL = 1e-6    # 軸がほぼ平行な相手は対象外(食い込みでなく継ぎ手)
_ALONG_TOL = 1.0        # 相手梁の軸方向の範囲判定の余裕(角部も含めるため端まで許容)
_FACE_TOL = 1.0         # 相手の面ちょうどで止まる材を食い込みとみなさない余裕
_MIN_TRIM = 1.0         # この値未満の食い込みは調整しない
_MIN_LENGTH = 1.0       # 調整後にこの長さ未満になる場合は調整しない
_SYMMETRY_TOL = 1.0     # 相互の食い込み量がこの差以内なら対称とみなし詰めない
_SLOPE_TOL = 1.0        # 両端の天端 Z の差がこの値以下なら水平材とみなす

# 軸の XY 成分がこれ以下の材は鉛直材(横架材でない)とみなしスキップする
_VERTICAL_AXIS_TOL = 1e-9


def _get_placement_3d(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float, float | None, float, float, float] | None:
    """IfcProduct のローカル配置から 3D 座標 (ox, oy, oz, ax, ay, az) を返す。

    取得できない場合は None を返す。oz は配置 Z 座標で、座標が 2 要素しか
    ない場合は None(呼び出し側でレイヤ基準高さにフォールバックする)。
    ax, ay, az は梁軸方向の 3D 単位ベクトル。ホームズ君 IFC では押し出し方向が
    常にローカル Z (Axis) なので梁の延伸方向 = Axis 属性を使う。登り梁・隅木等の
    傾斜梁は Axis に Z 成分を持つ。Axis が未設定の場合は (1.0, 0.0, 0.0) を使う。
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
    oz = float(coords[2]) if len(coords) >= 3 else None

    ax, ay, az = 1.0, 0.0, 0.0
    axis = rel.Axis
    if axis is not None and len(axis.DirectionRatios) >= 2:
        dx = float(axis.DirectionRatios[0])
        dy = float(axis.DirectionRatios[1])
        dz = float(axis.DirectionRatios[2]) if len(axis.DirectionRatios) >= 3 else 0.0
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if norm > 0.0:
            ax, ay, az = dx / norm, dy / norm, dz / norm

    return ox, oy, oz, ax, ay, az


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


def _sloped_member_geometry(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float, float, float, float, float, float, float, float] | None:
    """任意断面(平行四辺形の側面シルエット)を厚み方向に押し出した傾斜梁
    (登り梁等)の幾何情報を返す。矩形断面の材や対象外の材は None を返す。

    ホームズ君 IFC の登り梁は矩形断面(``IfcRectangleProfileDef`` を軸方向へ押し出し)
    ではなく、材の側面(長さ×せいの平行四辺形。端部の直切りでせん断される)を表す
    ``IfcArbitraryClosedProfileDef`` を厚み方向へ押し出したソリッドで表される。この
    ため ``_get_profile_dims`` では拾えず、対処しないと横架材から取りこぼされて描画
    されない。``footing._world_solid`` でワールド情報に変換し、平行四辺形の 4 頂点から
    断面の中心軸の一端 ``(ox, oy, oz)``・軸単位ベクトル ``(ax, ay, az)``・幅(厚み)・
    せい・中心軸長を導出する。以降は通常の横架材と同じ扱い(断面中心の配置点として
    天端中央線へ持ち上げる)にできる。

    Returns: ``(ox, oy, oz, ax, ay, az, width, height, length)``。``ox, oy, oz`` は
        中心軸の一端のワールド座標(ストーリ相対 Z)。矩形断面(通常の横架材が
        ``_get_profile_dims`` で処理する)・4 頂点でない断面(火打の footprint や
        筋かいの 6 頂点など)・解釈不能な場合は None。
    """
    solid = _world_solid(element)
    if solid is None:
        return None
    (origin, lx, ly, _lz), extrude, depth, pts, dims = solid
    if dims is not None:
        return None  # 矩形断面は通常経路(_get_profile_dims)が処理する
    if len(pts) != 4:
        return None  # 対象は平行四辺形(4 頂点)のみ。火打・筋かい等は除外する
    us = [u for u, _v in pts]
    vs = [v for _u, v in pts]
    u_span = max(us) - min(us)
    v_span = max(vs) - min(vs)
    if u_span <= 0.0 or v_span <= 0.0:
        return None
    # 長さ軸 = プロファイル 2D で span の大きい座標。せい = もう一方の span。
    # 幅(厚み)= 押し出し長。長辺(材の長さ方向)は長さ軸に沿う辺、端辺(直切り)は
    # もう 1 対で、その中心が中心軸の両端になる。
    length_is_u = u_span >= v_span
    height = v_span if length_is_u else u_span

    def along(edge: tuple[float, float]) -> float:
        return abs(edge[0]) if length_is_u else abs(edge[1])

    e0 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    e1 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    if along(e0) >= along(e1):
        # 長辺 = 辺 0-1・2-3、端辺 = 辺 1-2・3-0
        end_a = ((pts[1][0] + pts[2][0]) / 2.0, (pts[1][1] + pts[2][1]) / 2.0)
        end_b = ((pts[3][0] + pts[0][0]) / 2.0, (pts[3][1] + pts[0][1]) / 2.0)
    else:
        # 長辺 = 辺 1-2・3-0、端辺 = 辺 0-1・2-3
        end_a = ((pts[0][0] + pts[1][0]) / 2.0, (pts[0][1] + pts[1][1]) / 2.0)
        end_b = ((pts[2][0] + pts[3][0]) / 2.0, (pts[2][1] + pts[3][1]) / 2.0)

    half_w = depth / 2.0

    def to_world(c: tuple[float, float]) -> tuple[float, float, float]:
        base = _add(_add(origin, _scale(lx, c[0])), _scale(ly, c[1]))
        return _add(base, _scale(extrude, half_w))  # 断面中心(厚みの中央)へ寄せる

    ax_pt = to_world(end_a)
    bx_pt = to_world(end_b)
    axis = (bx_pt[0] - ax_pt[0], bx_pt[1] - ax_pt[1], bx_pt[2] - ax_pt[2])
    length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
    if length <= 0.0:
        return None
    ax, ay, az = axis[0] / length, axis[1] / length, axis[2] / length
    ox, oy, oz = ax_pt
    return ox, oy, oz, ax, ay, az, depth, height, length


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
    """2 つの横架材の Z 範囲([天端 - 背, 天端])が重なるか判定する。

    elevation は横架材天端の絶対高さで、断面は天端から背だけ下方に伸びる。
    重なりが許容値以下(段差で上下に離れている等)なら干渉とみなさない。
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

    T 字(相手の途中に突き当たる)・L 字(相手の端部で突き当たる)を区別せず、
    軸方向の位置 t は相手の端まで許容する。勝ち負けの判定は呼び出し側が
    相互の食い込み量を比較して行う。
    """
    pbx, pby = -uy, ux              # 相手梁の断面幅方向(中心線に直交する単位ベクトル)
    a = gx * pbx + gy * pby
    if abs(a) < _PARALLEL_TOL:
        return 0.0                  # ほぼ平行 → 食い込みではなく継ぎ手
    dpx, dpy = px - sx, py - sy
    d = dpx * pbx + dpy * pby       # 相手中心線からの符号付き距離
    if abs(d) > hw + _FACE_TOL:
        return 0.0                  # 端点が相手の幅の外(食い込んでいない)
    t = dpx * ux + dpy * uy         # 相手軸方向の位置
    if not (-_ALONG_TOL < t < length + _ALONG_TOL):
        return 0.0                  # 相手の長さの範囲外
    # 端点が侵入してきた側(手前)の面まで引き戻す距離
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
    sBA より大きい(= B の方が「通し材」側で勝ち)場合のみ詰める。相互の
    食い込み量が同等(対称な角・火打等)なら触らない。複数の相手に食い込む
    場合は、すべての面より外側になるよう最大値を採用する。
    """
    asx, asy, _aex, _aey, aux, auy, _alen = self_geom
    best = 0.0
    for (bsx, bsy, bex, bey, bux, buy, blen), b_hw in others:
        s_ab = _penetration_depth(px, py, gx, gy, bsx, bsy, bux, buy, blen, b_hw)
        if s_ab <= _MIN_TRIM:
            continue
        # 相手 B の 2 端点が自分 A に食い込む量(B 始端の外向きは -軸、終端は +軸)
        s_ba = max(
            _penetration_depth(bsx, bsy, -bux, -buy, asx, asy, aux, auy, _alen, self_hw),
            _penetration_depth(bex, bey, bux, buy, asx, asy, aux, auy, _alen, self_hw),
        )
        # 自分の方が深く食い込む(相手が勝ち)ときだけ詰める。対称なら触らない。
        if s_ab > s_ba + _SYMMETRY_TOL and s_ab > best:
            best = s_ab
    return best


def resolve_member_interferences(
    commands: list[MemberCommand],
) -> list[MemberCommand]:
    """横架材同士の食い込み(T 字・L 字の取り合い)を解消するよう端部を詰める。

    ある横架材の端点が別の横架材の矩形に食い込み、かつ Z 範囲・配置レイヤが
    一致する場合、相手梁の手前の面まで端点を引き戻す。ただし相互の食い込み量
    を比べ、自分の方が深く食い込む(相手が「通し材」で勝ち)ときだけ詰める。
    相互の食い込み量が同等な対称の角(火打等)は勝ち負けが付かないため触らない。
    相手梁の形状は変えず、食い込む側のみ短くする。

    傾斜梁(登り梁・隅木等、両端の天端 Z が異なる材)は高さが一定でなく
    水平面内の矩形モデルが成り立たないため、詰める側にも相手側にもしない。

    判定は入力時点のジオメトリ(スナップショット)に対して行うため、
    命令の並び順に依存しない決定的な結果になる。入力 commands は変更せず、
    調整後の新しいリストを返す。
    """
    geoms: list[_Geom | None] = []
    for c in commands:
        if abs(c['end_elevation'] - c['elevation']) > _SLOPE_TOL:
            geoms.append(None)  # 傾斜梁は調整対象外
            continue
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
            'class': command['class'],
            'start': new_start,
            'end': new_end,
            'width': command['width'],
            'height': command['height'],
            'elevation': command['elevation'],
            'end_elevation': command['end_elevation'],
            # 端部の詰めは平面座標 (XY) のみ変えるため高さバインドはそのまま
            'start_bound': command['start_bound'],
            'end_bound': command['end_bound'],
        })

    return result


def build_member_commands(ifc_file: ifcopenshell.file) -> list[MemberCommand]:
    """IFC の横架材から member 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    最上階(屋根)には横架材天端レイヤが存在しないため軒高レイヤを指定する。
    ただし母屋・棟木(小屋組の上端材)は梁と重なって見にくいため、横架材天端
    (最上階は軒高)レイヤと分けた母屋レイヤ(n-母屋)に配置する。最上階の主屋根
    だけでなく、中間階に架かる下屋根(下屋)の母屋・棟木も同様に分離する。
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

                placement = _get_placement_3d(element)
                if placement is None:
                    continue

                # 軸(押し出し方向)が鉛直な材は横架材でないためスキップ(火打等)。
                # 断面種別(矩形/任意)より先に判定して火打を確実に除外する。
                if math.hypot(placement[3], placement[4]) <= _VERTICAL_AXIS_TOL:
                    continue

                dims = _get_profile_dims(element)
                if dims is not None:
                    ox, oy, oz, ax, ay, az = placement
                    width, height, length = dims
                    vertical_cut = False
                else:
                    # 矩形断面で拾えない材は、登り梁等の傾斜梁(任意断面=平行四辺形の
                    # 側面を厚み方向に押し出したソリッド)として中心軸を導出する。
                    # 平行四辺形として解釈できない材(筋かいの 6 頂点等)はスキップ。
                    sloped = _sloped_member_geometry(element)
                    if sloped is None:
                        continue
                    ox, oy, oz, ax, ay, az, width, height, length = sloped
                    # 登り梁は端部が直切り(鉛直面)。下の高さ補正で矩形前提の軸直交
                    # 持ち上げでなく直切りの幾何(XY ずらし無し・鉛直持ち上げ)を使う。
                    vertical_cut = True

                horiz = math.hypot(ax, ay)
                if horiz <= _VERTICAL_AXIS_TOL:
                    continue

                # 断面中心線の始端・終端(傾斜梁は軸の Z 成分で終端の高さが変わる。
                # 平面座標も軸の XY 成分 × 全長で求め、平面投影長を正しくする)
                x1 = ox - center_x
                y1 = oy - center_y
                x2 = x1 + ax * length
                y2 = y1 + ay * length

                # 各横架材は固定の横架材天端高さではなく、IFC 上の実際の
                # ローカル配置 Z で描画する。基準高さ(横架材天端)にない梁も
                # 正しい高さに配置するため。Z が取得できない梁のみレイヤ基準高さを使う。
                # IFC の配置点は断面中心なので、構造材ツールの断面基準点
                # (左右中央・上端)に合わせて天端中央線を求める。
                if oz is None:
                    # レイヤ基準高さ(横架材天端)は既に天端の高さなので補正不要
                    elevation = layer_elevation
                    end_elevation = layer_elevation
                elif vertical_cut:
                    # 登り梁: 端部は直切り(鉛直面)。断面中心軸は鉛直な端面の中央高さを
                    # 通るため、天端中央線の端点は端面中央の**直上**(XY は同じ)= 鉛直な
                    # 端面の上端にあり、高さは 断面中心 + せい/(2·cosθ)(cosθ=horiz)。
                    # 矩形前提の軸直交持ち上げ(下の else)を登り梁に使うと、
                    #  (1) 天端が (せい/2)(secθ − cosθ) だけ低くなり、垂木下面(屋根勾配)に
                    #      届かない(始端・終端の高さを垂木下面に合わせる要件)、
                    #  (2) 端部が勾配ぶん(せい/2·sinθ)軒側へずれ、上端を受ける柱との間に
                    #      水平の隙間ができる(登り梁を柱が受ける端の隙間を無くす要件)、
                    # の 2 点が生じる。直切りの幾何(XY ずらし無し・鉛直持ち上げ)にして
                    # 天端を屋根勾配=垂木下面に合わせ、端部を柱に密着させる。
                    half = height / 2.0
                    elevation = storey_elevation + oz + half / horiz
                    end_elevation = elevation + az * length
                else:
                    # 軸に直交し軸を含む鉛直面内で上向きの単位ベクトル n の方向に
                    # 背/2 だけ持ち上げ天端中央線にする(端部が軸直交切りの傾斜梁・水平梁)。
                    nx = -az * ax / horiz
                    ny = -az * ay / horiz
                    nz = horiz
                    half = height / 2.0
                    x1 += nx * half
                    y1 += ny * half
                    x2 += nx * half
                    y2 += ny * half
                    elevation = storey_elevation + oz + nz * half
                    end_elevation = elevation + az * length

                material = _get_material_name(element)
                member_id = make_member_id(width, height, material)

                # クラスは IFC 名の種別で判別する。判別できない部材は階・高さで
                # 推定する(最上階は天端が軒高を超える材を母屋、軒高付近を小屋梁)。
                above_eaves = max(elevation, end_elevation) > layer_elevation + _SLOPE_TOL
                member_class = resolve_member_class(
                    element.Name, i, top_idx, above_eaves)

                # 母屋・棟木(小屋組の上端材)は梁(小屋梁・軒桁)と重なって見にくい
                # ため、横架材天端(最上階は軒高)レイヤと分けた母屋レイヤ(n-母屋)に
                # 配置し、高さ基準も母屋レベルにバインドする。母屋レベルは横架材天端
                # (最上階は軒高)と同じ絶対 Z(offset=column_offset、最上階は 0)なので
                # layer_elevation は変わらず offset の算出はそのまま。最上階(屋根)の
                # 主屋根だけでなく、中間階に架かる下屋根(下屋)の母屋・棟木も同様に
                # 分離する(story.py が該当階に母屋レベルを作る条件と一致する)。
                if member_class in (CLASS_MOYA, CLASS_MUNAGI):
                    element_layer_name = f'{prefix}-{LEVEL_MOYA}'
                    bound_level = LEVEL_MOYA
                elif member_class == CLASS_NOBORIBARI:
                    # 登り梁も母屋・棟木と同じスキームで専用レイヤ(n-登り梁)に分離する。
                    # 母屋レベルと同じ絶対 Z(offset=column_offset)なので offset 算出は
                    # 横架材と変わらず、傾斜は始端/終端の offset 差として表れる。
                    element_layer_name = f'{prefix}-{LEVEL_NOBORIBARI}'
                    bound_level = LEVEL_NOBORIBARI
                else:
                    element_layer_name = layer_name
                    bound_level = layer_suffix

                # 高さ基準を配置先レイヤのストーリレベル(横架材天端、最上階は軒高、
                # 母屋は母屋)にバインドする。offset はレベルの絶対 Z(layer_elevation)
                # から天端 Z までの距離。平らな梁は ≈0、段差梁は一定値、傾斜梁は
                # 始端/終端で異なる値になる。
                start_bound: StoryBoundCommand = {
                    'story_offset': 0, 'level': bound_level,
                    'offset': elevation - layer_elevation}
                end_bound: StoryBoundCommand = {
                    'story_offset': 0, 'level': bound_level,
                    'offset': end_elevation - layer_elevation}

                commands.append({
                    'layer': element_layer_name,
                    'member_id': member_id,
                    'class': member_class,
                    'start': [x1, y1],
                    'end': [x2, y2],
                    'width': width,
                    'height': height,
                    'elevation': elevation,
                    'end_elevation': end_elevation,
                    'start_bound': start_bound,
                    'end_bound': end_bound,
                })

    # 横架材同士が食い込んでいる箇所は端部の長さを詰めて干渉を解消する
    return resolve_member_interferences(commands)
