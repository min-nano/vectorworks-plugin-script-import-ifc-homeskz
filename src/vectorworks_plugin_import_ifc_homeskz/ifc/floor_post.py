"""床束の解析と floor_post 命令の組み立て。vs 非依存。

ホームズ君 EX の IFC には**床束が出力されない**(オブジェクト・型・プロパティの
いずれにも床束・束の位置や仕様が現れない)。そのため床束は IFC から抽出できず、
要件どおり**大引の下に一定間隔(910mm)で決め打ち配置**する。

- 対象: ``Name`` の種別が ``大引``(``member_class_from_name`` が
  ``CLASS_OOBIKI`` を返す)の IfcBeam / IfcMember。
- 配置の基準(端部): 大引の**実部材端**ではなく、**その端を受けている支持材の芯**
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

_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')

# 大引を受ける支持材の種別(土台・他の大引)。
_SUPPORT_CLASSES = (CLASS_DODAI, CLASS_OOBIKI)

# 支持材 1 本の平面芯線。(始点 x, y, 単位方向 x, y, 芯線長, 幅)。
_SupportLine = tuple[float, float, float, float, float, float]


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


def build_floor_post_commands(
    ifc_file: ifcopenshell.file,
) -> list[FloorPostCommand]:
    """大引の下に床束(ハイブリッドシンボル)を配置する floor_post 命令を組み立てる。

    IFC に床束が無いため、大引(``CLASS_OOBIKI``)の下に 910mm 間隔で床束を並べる。
    間隔の基準(端部)は大引の実部材端ではなく、その端を受けている支持材(土台・
    他の大引)の芯とする(``_shin_reference``)。座標は通り芯・横架材と同じグリッド
    中心オフセットで補正する。高さの基準(基礎底盤上端)は配置先レイヤ ``F-床束`` の
    ストーリレベルが担うため命令には高さ情報を持たせない。基礎が無いモデルでは
    空リストを返す。
    """
    if not has_foundation(ifc_file):
        return []

    _, center_x, center_y = resolve_lines(ifc_file)
    support_lines = _collect_support_lines(ifc_file)

    elements: list[ifcopenshell.entity_instance] = []
    for member_type in _IFC_MEMBER_TYPES:
        elements += ifc_file.by_type(member_type)

    commands: list[FloorPostCommand] = []
    for element in elements:
        if member_class_from_name(element.Name) != CLASS_OOBIKI:
            continue
        placement = _get_placement_3d(element)
        if placement is None:
            continue
        dims = _get_profile_dims(element)
        if dims is None:
            continue

        ox, oy, _oz, ax, ay, _az = placement
        _width, _height, length = dims

        # 実部材の平面芯線(始点・終点)。傾斜大引でも平面投影の芯線に沿って並べる。
        sx, sy = ox, oy
        ex, ey = ox + ax * length, oy + ay * length
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
