"""床束の解析と floor_post 命令の組み立て。vs 非依存。

ホームズ君 EX の IFC には**床束が出力されない**(オブジェクト・型・プロパティの
いずれにも床束・束の位置や仕様が現れない)。そのため床束は IFC から抽出できず、
要件どおり**大引の下に一定間隔(910mm)で決め打ち配置**する。

- 対象: ``Name`` の種別が ``大引``(``member_class_from_name`` が
  ``CLASS_OOBIKI`` を返す)の IfcBeam / IfcMember。
- 継手の統合: ホームズ君 IFC の大引は継手(支持材の上での継目)で分断されているが、
  継手は実際の大引の端ではない。**同一直線上で継手(すき間 ≤ 半モジュール)で分断
  された大引は 1 連に統合**してから配置を計算する(``_merge_collinear_ohbiki``。継手は
  無いものとして 910mm 間隔を通しで割り付ける)。同一直線上でも 1 モジュール以上離れた
  別々の大引は統合しない。
- 配置の基準(端部): 統合後の大引 1 連の**実部材端**ではなく、**その端を受けている支持材の芯**
  (土台または他の大引の芯=支持材芯)を端部とする。ホームズ君 IFC の大引は端部が
  支持材芯より半支持材厚だけ内側に納まって描かれており(単モジュール=910mm 区間で
  実長 805mm=910−105)、実部材端を基準にすると床束が実際より内側に寄る。各端で
  大引の芯線と交わる支持材(土台・他の大引)の芯線の交点(=支持材芯)を求め、その
  交点を端部として扱う(``_shin_reference``)。**二次大引(他の大引の上に載る大引)の
  端も、受けている大引の芯を端部にする**。自身の芯線・同一直線上の大引は平行のため
  除外され、どの支持材にも受けられていない端(基礎に直接載る端等)は実部材端に
  フォールバックする。
- 位置: 支持材芯どうしの区間に沿って、**始点側の支持材芯(端部)から ``910mm`` ずつ**
  床束を並べる(``_post_offsets``)。始点の支持材芯から 910mm・1820mm・… の位置に
  床束を置き、最後の床束と終点側の支持材芯(反対側の端部)との間隔は 910mm 未満の
  半端になってよい。支持材芯そのものには床束を置かない(端部は支持材が受ける)。
  支持材芯区間が 910mm 以下の大引には床束を置かない。
- 高さの基準: 基礎底盤上端(底盤天端)。命令には高さ情報を持たせず、配置先レイヤ
  ``F-床束`` のストーリレベル(床束=底盤天端に揃える)が担う。
- 置換シンボル: ハイブリッドシンボル ``床束``。

床束は基礎(底盤)の上に立つため、基礎が無いモデル(``has_foundation`` が False)
では配置先レイヤ ``F-床束`` が生成されず高さ基準も定まらないため空リストを返す。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import FloorPostCommand
from .footing import has_foundation
from .grid import resolve_lines
from .member import _get_placement_3d, _get_profile_dims
from .story import LAYER_FOUNDATION_FLOOR_POST
from .structural_class import CLASS_DODAI, CLASS_OOBIKI, member_class_from_name

if TYPE_CHECKING:
    import ifcopenshell

# 置換するハイブリッドシンボル名
SYMBOL_FLOOR_POST = '床束'

# 床束の配置間隔 (mm)。IFC に床束が無いための決め打ち値(半間=910mm)。
_POST_INTERVAL = 910.0

# 支持材芯の探索許容値 (mm)
_PARALLEL_TOL = 1e-9    # 芯線がほぼ平行な支持材は交点が定まらないため対象外
_SEG_TOL = 1.0          # 交点が支持材の区間からこの値だけはみ出しても受けとみなす
_SHIN_MARGIN = 1.0      # 大引端が支持材の footprint(半支持材厚)+この値以内なら受けとみなす

# 同一直線上の大引の継手(継目)判定の許容値 (mm)
_COLLINEAR_ANGLE_TOL = 1e-6     # 方向ベクトルの外積(=sin 角)がこれ以下なら平行
_COLLINEAR_PERP_TOL = 1.0       # 相手端の芯線からの直交距離がこれ以下なら同一直線上
# 継手のすき間(継目=支持材幅ぶんの間隔)がこれ以下の同一直線上の大引は 1 本に統合。
# 継手のすき間(支持材幅≈105mm)は半モジュール(455mm)を大きく下回り、別々の大引の
# 間隔(≥1 モジュール≈1000mm)を大きく下回るため、この値で継手と別材を切り分けられる。
_JOINT_GAP_TOL = _POST_INTERVAL / 2.0

_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')

# 大引を受ける支持材の種別(土台・他の大引)。
_SUPPORT_CLASSES = (CLASS_DODAI, CLASS_OOBIKI)

# 支持材 1 本の平面芯線。(始点 x, y, 単位方向 x, y, 芯線長, 幅)。
_SupportLine = tuple[float, float, float, float, float, float]

# 大引 1 本(または継手で統合した 1 連)の平面芯線。(始点 x, y, 終点 x, y)。
_OhbikiRun = tuple[float, float, float, float]


def _post_offsets(length: float) -> list[float]:
    """支持材芯区間 1 つに沿った床束の配置位置(始点側の支持材芯からの距離)を返す。

    始点側の支持材芯(端部)から ``_POST_INTERVAL`` ずつ、``910mm``・``1820mm``・… の
    位置に床束を並べる。最後の床束と終点側の支持材芯(反対側の端部)との間隔は 910mm
    未満の半端になってよい。支持材芯そのものには床束を置かない(端部は支持材が受ける)
    ため、終点ちょうど以遠には置かない。支持材芯区間が 910mm 以下の大引は床束 0 本
    (両端が 910mm 以内で受けられる)。
    """
    if length <= 0.0:
        return []
    offsets: list[float] = []
    k = 1
    while _POST_INTERVAL * k < length:
        offsets.append(_POST_INTERVAL * k)
        k += 1
    return offsets


def _collect_support_lines(ifc_file: ifcopenshell.file) -> list[_SupportLine]:
    """大引を受ける支持材(土台・大引)の平面芯線を集める。

    座標はグリッド中心オフセット前の生値。土台だけでなく他の大引も含めることで、
    他の大引の上に載る二次大引の端も支持材芯を基準にできる(自身の芯線・同一直線上
    の大引は ``_shin_reference`` の平行判定で除外される)。
    """
    lines: list[_SupportLine] = []
    for member_type in _IFC_MEMBER_TYPES:
        for element in ifc_file.by_type(member_type):
            if member_class_from_name(element.Name) not in _SUPPORT_CLASSES:
                continue
            placement = _get_placement_3d(element)
            dims = _get_profile_dims(element)
            if placement is None or dims is None:
                continue
            ox, oy, _oz, ax, ay, _az = placement
            width, _height, length = dims
            ex, ey = ox + ax * length, oy + ay * length
            seg_len = math.hypot(ex - ox, ey - oy)
            if seg_len <= 0.0:
                continue
            lines.append((ox, oy, (ex - ox) / seg_len, (ey - oy) / seg_len, seg_len, width))
    return lines


def _shin_reference(
    px: float,
    py: float,
    ux: float,
    uy: float,
    support_lines: list[_SupportLine],
) -> tuple[float, float] | None:
    """大引端 ``(px, py)`` を受けている支持材(土台・大引)の芯(交点)を返す。無ければ None。

    大引の芯線(点 ``(px, py)``・方向 ``(ux, uy)``)と各支持材の芯線の交点を求め、
    交点が支持材の区間内にあり、かつ大引端から半支持材厚(+``_SHIN_MARGIN``)以内に
    ある(=大引端がその支持材の footprint に載っている)支持材のうち、最も近い交点を
    支持材芯として返す。平行な支持材(自身の芯線・同一直線上の大引を含む)は交点が
    定まらないため除外する。
    """
    best_t: float | None = None
    best_point: tuple[float, float] | None = None
    for bx, by, vx, vy, seg_len, width in support_lines:
        den = ux * vy - uy * vx
        if abs(den) < _PARALLEL_TOL:
            continue
        rx, ry = bx - px, by - py
        t = (rx * vy - ry * vx) / den    # 大引芯上のパラメータ(端からの符号付き距離)
        s = (rx * uy - ry * ux) / den    # 支持材芯上のパラメータ
        if s < -_SEG_TOL or s > seg_len + _SEG_TOL:
            continue
        if abs(t) > width / 2.0 + _SHIN_MARGIN:
            continue
        if best_t is None or abs(t) < abs(best_t):
            best_t = t
            best_point = (px + t * ux, py + t * uy)
    return best_point


def _collect_ohbiki_lines(ifc_file: ifcopenshell.file) -> list[_OhbikiRun]:
    """大引(``CLASS_OOBIKI``)の平面芯線を集める(始点・終点、グリッド中心オフセット前)。"""
    lines: list[_OhbikiRun] = []
    for member_type in _IFC_MEMBER_TYPES:
        for element in ifc_file.by_type(member_type):
            if member_class_from_name(element.Name) != CLASS_OOBIKI:
                continue
            placement = _get_placement_3d(element)
            dims = _get_profile_dims(element)
            if placement is None or dims is None:
                continue
            ox, oy, _oz, ax, ay, _az = placement
            _width, _height, length = dims
            ex, ey = ox + ax * length, oy + ay * length
            if math.hypot(ex - ox, ey - oy) <= 0.0:
                continue
            lines.append((ox, oy, ex, ey))
    return lines


def _collinear_gap(a: _OhbikiRun, b: _OhbikiRun) -> float | None:
    """大引 a・b が同一直線上にあるとき、区間のすき間(重なり/接触は 0)を返す。

    (1) 方向が平行、(2) b の端点が a の芯線上(直交距離 ≈ 0)、を満たすとき、a 方向に
    射影した b の区間と a の区間 [0, la] のすき間を返す(重なる/接触するなら 0)。
    平行でない/別の直線上にある(直交距離が大きい)場合は None。
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dax, day = ax2 - ax1, ay2 - ay1
    la = math.hypot(dax, day)
    dbx, dby = bx2 - bx1, by2 - by1
    lb = math.hypot(dbx, dby)
    if la <= 0.0 or lb <= 0.0:
        return None
    ux, uy = dax / la, day / la
    if abs(ux * (dby / lb) - uy * (dbx / lb)) > _COLLINEAR_ANGLE_TOL:
        return None
    if abs(ux * (by1 - ay1) - uy * (bx1 - ax1)) > _COLLINEAR_PERP_TOL:
        return None
    tb1 = ux * (bx1 - ax1) + uy * (by1 - ay1)
    tb2 = ux * (bx2 - ax1) + uy * (by2 - ay1)
    b_lo, b_hi = min(tb1, tb2), max(tb1, tb2)
    if b_lo > la:
        return b_lo - la
    if b_hi < 0.0:
        return -b_hi
    return 0.0


def _merge_collinear_ohbiki(lines: list[_OhbikiRun]) -> list[_OhbikiRun]:
    """同一直線上で継手(すき間 ≤ ``_JOINT_GAP_TOL``)の大引を 1 連に統合する。

    ホームズ君 IFC の大引は継手(支持材の上での継目)で分断されているが、継手は
    実際の大引の端ではないため、床束の間隔計算では 1 本と考える(要件)。Union-Find で
    同一直線上・すき間許容内の大引を連結成分にまとめ、各成分を先頭の芯線方向へ全端点を
    射影した最小〜最大区間の 1 本にする。統合は入力順に依存しない(代表は最小インデックス、
    出力は代表インデックス昇順)。
    """
    n = len(lines)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            gap = _collinear_gap(lines[i], lines[j])
            if gap is not None and gap <= _JOINT_GAP_TOL:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    runs: list[_OhbikiRun] = []
    for root in sorted(components):
        members = [lines[i] for i in components[root]]
        if len(members) == 1:
            runs.append(members[0])
            continue
        ax1, ay1, ax2, ay2 = members[0]
        la = math.hypot(ax2 - ax1, ay2 - ay1)
        ux, uy = (ax2 - ax1) / la, (ay2 - ay1) / la
        ts = [ux * (px - ax1) + uy * (py - ay1)
              for run in members for px, py in ((run[0], run[1]), (run[2], run[3]))]
        t_lo, t_hi = min(ts), max(ts)
        runs.append((ax1 + ux * t_lo, ay1 + uy * t_lo, ax1 + ux * t_hi, ay1 + uy * t_hi))
    return runs


def build_floor_post_commands(
    ifc_file: ifcopenshell.file,
) -> list[FloorPostCommand]:
    """大引の下に床束(ハイブリッドシンボル)を配置する floor_post 命令を組み立てる。

    IFC に床束が無いため、大引(``CLASS_OOBIKI``)の下に 910mm 間隔で床束を並べる。
    同一直線上で継手により分断された大引は 1 連に統合してから配置を計算する
    (``_merge_collinear_ohbiki``。継手は実際の大引の端ではないため)。間隔の基準(端部)は
    大引の実部材端ではなく、その端を受けている支持材(土台・他の大引)の芯とする
    (``_shin_reference``)。座標は通り芯・横架材と同じグリッド中心オフセットで補正する。
    高さの基準(基礎底盤上端)は配置先レイヤ ``F-床束`` のストーリレベルが担うため命令には
    高さ情報を持たせない。基礎が無いモデルでは空リストを返す。
    """
    if not has_foundation(ifc_file):
        return []

    _, center_x, center_y = resolve_lines(ifc_file)
    support_lines = _collect_support_lines(ifc_file)
    runs = _merge_collinear_ohbiki(_collect_ohbiki_lines(ifc_file))

    commands: list[FloorPostCommand] = []
    for sx, sy, ex, ey in runs:
        seg = math.hypot(ex - sx, ey - sy)
        if seg <= 0.0:
            continue
        ux, uy = (ex - sx) / seg, (ey - sy) / seg

        # 端部を実部材端ではなく支持材芯にする(受ける支持材が無ければ実部材端に戻す)。
        start = _shin_reference(sx, sy, ux, uy, support_lines) or (sx, sy)
        end = _shin_reference(ex, ey, ux, uy, support_lines) or (ex, ey)
        span = (end[0] - start[0]) * ux + (end[1] - start[1]) * uy
        if span <= 0.0:
            continue

        for distance in _post_offsets(span):
            commands.append({
                'layer': LAYER_FOUNDATION_FLOOR_POST,
                'symbol': SYMBOL_FLOOR_POST,
                'position': [start[0] + ux * distance - center_x,
                             start[1] + uy * distance - center_y],
            })
    return commands
