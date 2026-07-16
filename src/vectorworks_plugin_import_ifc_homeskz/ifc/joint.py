"""仕口(受ける材のある横架材端部)の解析と joint 命令の組み立て。vs 非依存。

横架材(``ifc/member.py`` が組み立てた member 命令)の端部が、別の横架材
(=受ける材)に取り付いているかを平面ジオメトリから判定し、取り付いている
端部にだけ仕口シンボル(``仕口``)を置く joint 命令を組み立てる。

要件:

- **受ける材のある横架材端部にだけ置く**。横架材の端点が、同じレイヤ・Z 範囲が
  重なる別の横架材(受ける材)の footprint(矩形)に取り付く(内部・面上に載る)
  場合を「受ける材のある端部」とする。どの横架材にも取り付かない自由端には
  置かない。
- **基準点は梁端の中央上端**。member 命令の ``start``/``end`` は断面の左右中央・
  上端(天端中央)が通る線の端点なので、その端点をそのまま基準点にする。
- **横架材レイヤに描画する**。member 命令の配置レイヤ(横架材天端、最上階は軒高、
  母屋は母屋)をそのまま使う。

受ける材の判定は横架材どうし(同一レイヤ)の食い込み調整
(``ifc/member.py`` の ``resolve_member_interferences``)と同じ方針にそろえる。
すなわち、平行(同一直線上の継ぎ手・側並びの平行材)は受ける材とみなさず、
軸が交差する材だけを対象にする。判定は member 命令のジオメトリ(食い込み調整済み)
に対して行い、命令の並び順に依存しない決定的な結果になる。

**回転角**は梁端の向きに合わせ、梁軸に沿って端部から部材内側へ向かう方向にする
(シンボルが梁と揃うようにする)。シンボルの基準姿勢は VectorWorks 上で最終確認
する(描画フェーズは他要素と同じく VW 上で検証する方針)。
"""
from __future__ import annotations

import math

from ..document import JointCommand, MemberCommand

# 置換するハイブリッドシンボル名
SYMBOL_JOINT = '仕口'

# 受ける材の判定に使う許容値 (mm)。横架材の食い込み調整(member.py)と同じ考え方。
_PARALLEL_TOL = 1e-6    # 軸がほぼ平行な相手は受ける材とみなさない(継ぎ手・側並び)
_ALONG_TOL = 1.0        # 相手材の軸方向の範囲判定の余裕(端部=コーナーも含めるため)
_FACE_TOL = 1.0         # 相手材の面ちょうどに載る端部も取り付きとみなす余裕
_Z_OVERLAP_TOL = 1.0    # この値以下の Z 重なりは取り付きとみなさない(段差材は対象外)
_MIN_LENGTH = 1.0       # 平面投影長がこの値未満の材は端部・向きが定まらずスキップ

# 梁ジオメトリ: (start_x, start_y, end_x, end_y, ux, uy, length, hw, z_bottom, z_top)
_Geom = tuple[float, float, float, float, float, float, float, float, float, float]


def _member_geom(command: MemberCommand) -> _Geom | None:
    """member 命令から受ける材判定用のジオメトリを返す。

    平面座標(天端中央線の端点)・単位軸ベクトル・平面投影長・半幅・Z 範囲
    ([天端下端, 天端上端])を計算する。平面投影長が極小の材は None を返す。
    Z 範囲は傾斜梁(elevation ≠ end_elevation)も含めて実体の下端〜上端を覆う。
    """
    sx, sy = command['start']
    ex, ey = command['end']
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy)
    if length < _MIN_LENGTH:
        return None
    ux, uy = dx / length, dy / length
    hw = command['width'] / 2.0
    height = command['height']
    z_top = max(command['elevation'], command['end_elevation'])
    z_bottom = min(command['elevation'], command['end_elevation']) - height
    return sx, sy, ex, ey, ux, uy, length, hw, z_bottom, z_top


def _z_overlaps(a: _Geom, b: _Geom) -> bool:
    """2 材の Z 範囲([天端下端, 天端上端])が許容値を超えて重なるか判定する。"""
    _asx, _asy, _aex, _aey, _aux, _auy, _alen, _ahw, a_bottom, a_top = a
    _bsx, _bsy, _bex, _bey, _bux, _buy, _blen, _bhw, b_bottom, b_top = b
    return min(a_top, b_top) - max(a_bottom, b_bottom) > _Z_OVERLAP_TOL


def _point_in_member(px: float, py: float, other: _Geom) -> bool:
    """端点 (px, py) が相手材 ``other`` の footprint(矩形)に入るか判定する。

    相手材の中心線(始点・軸 (ux, uy)・長さ length)からの軸方向位置 t が
    [0, length](端=コーナーの余裕 ``_ALONG_TOL`` を含む)にあり、直交方向の
    距離が半幅 + ``_FACE_TOL`` 以内(面ちょうどに載る端部も含む)なら取り付き。
    """
    sx, sy, _ex, _ey, ux, uy, length, hw, _zb, _zt = other
    dpx, dpy = px - sx, py - sy
    t = dpx * ux + dpy * uy               # 相手軸方向の位置
    if not (-_ALONG_TOL <= t <= length + _ALONG_TOL):
        return False
    perp = dpx * (-uy) + dpy * ux         # 相手中心線からの直交距離
    return abs(perp) <= hw + _FACE_TOL


def _end_has_receiver(
    index: int, px: float, py: float,
    geoms: list[_Geom | None], members: list[MemberCommand],
) -> bool:
    """端点 (px, py) に取り付く受ける材(別の横架材)があれば True。

    同一レイヤ・Z 範囲が重なる・軸が交差する(平行でない)別の横架材の
    footprint に端点が入る相手が 1 つでもあれば受ける材ありとみなす。
    平行な相手(同一直線上の継ぎ手・側並びの平行材)は受ける材にしない。
    """
    gi = geoms[index]
    if gi is None:
        return False
    _isx, _isy, _iex, _iey, iux, iuy, _ilen, _ihw, _izb, _izt = gi
    layer = members[index]['layer']
    for j, gj in enumerate(geoms):
        if j == index or gj is None:
            continue
        if members[j]['layer'] != layer:
            continue
        _jsx, _jsy, _jex, _jey, jux, juy, _jlen, _jhw, _jzb, _jzt = gj
        # 平行(継ぎ手・側並び)は受ける材とみなさない
        if abs(iux * juy - iuy * jux) < _PARALLEL_TOL:
            continue
        if not _z_overlaps(gi, gj):
            continue
        if _point_in_member(px, py, gj):
            return True
    return False


def build_joint_commands(members: list[MemberCommand]) -> list[JointCommand]:
    """横架材の member 命令から joint 命令のリストを組み立てる。

    横架材の端部(始端・終端)ごとに、受ける材(別の横架材)に取り付くかを判定し、
    取り付く端部にだけ仕口シンボルを置く。基準点は梁端の中央上端(member 命令の
    端点)、配置レイヤは横架材と同じレイヤ、回転角は梁軸に沿って端部から内側へ
    向かう方向。member 命令のジオメトリ(食い込み調整済み)に対して判定するため、
    命令の並び順に依存しない決定的な結果になる。
    """
    geoms: list[_Geom | None] = [_member_geom(m) for m in members]

    commands: list[JointCommand] = []
    for i, member in enumerate(members):
        gi = geoms[i]
        if gi is None:
            continue
        sx, sy, ex, ey, ux, uy, _len, _hw, _zb, _zt = gi
        # 始端(内側方向は +軸)・終端(内側方向は -軸)の順に判定する
        for (px, py), (ix, iy) in (
            ((sx, sy), (ux, uy)),
            ((ex, ey), (-ux, -uy)),
        ):
            if not _end_has_receiver(i, px, py, geoms, members):
                continue
            commands.append({
                'layer': member['layer'],
                'symbol': SYMBOL_JOINT,
                'position': [px, py],
                'angle': math.degrees(math.atan2(iy, ix)),
            })

    return commands
