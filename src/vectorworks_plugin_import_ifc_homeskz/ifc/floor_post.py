"""床束の解析と floor_post 命令の組み立て。vs 非依存。

ホームズ君 EX の IFC には**床束が出力されない**(オブジェクト・型・プロパティの
いずれにも床束・束の位置や仕様が現れない)。そのため床束は IFC から抽出できず、
要件どおり**大引の下に一定間隔(910mm)で決め打ち配置**する。

- 対象: ``Name`` の種別が ``大引``(``member_class_from_name`` が
  ``CLASS_OOBIKI`` を返す)の IfcBeam / IfcMember。
- 位置: 各大引の平面芯線に沿って ``910mm`` 間隔で床束を並べる。芯線長を 910mm に
  最も近い整数個の区間(スパン)に等分し、**各区間の中央**に床束を置く
  (``_post_offsets``)。ホームズ君 IFC の大引は通り芯間で ``n×910−105mm`` の
  短い区間に分断されており(単モジュールの大引は 805mm)、端点(=大引が土台や
  隣の大引・基礎に載る継ぎ目)は隣の部材が受けるため床束を置かず、各スパンの
  中央を 1 本ずつ受ける。これにより短い単モジュールの大引にも床束が 1 本入り、
  かつ床束のピッチが 910mm 前後(≤910mm)に収まる。
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
from .structural_class import CLASS_OOBIKI, member_class_from_name

if TYPE_CHECKING:
    import ifcopenshell

# 置換するハイブリッドシンボル名
SYMBOL_FLOOR_POST = '床束'

# 床束の配置間隔 (mm)。IFC に床束が無いための決め打ち値(半間=910mm)。
_POST_INTERVAL = 910.0

_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')


def _post_offsets(length: float) -> list[float]:
    """大引 1 本の芯線に沿った床束の配置位置(始点からの距離)を返す。

    芯線長を ``_POST_INTERVAL`` に最も近い整数個の区間(スパン)に等分し、各区間の
    **中央**を返す。区間数は ``max(1, round(length / 910))`` なので、910mm 未満の
    短い大引でも区間 1 = 中央に床束が 1 本入り、長い大引は 910mm 前後(≤910mm)の
    ピッチで床束が並ぶ。端点には床束を置かない(端部は土台・隣の大引・基礎が受ける)。
    """
    if length <= 0.0:
        return []
    gaps = max(1, round(length / _POST_INTERVAL))
    return [length * (i + 0.5) / gaps for i in range(gaps)]


def build_floor_post_commands(
    ifc_file: ifcopenshell.file,
) -> list[FloorPostCommand]:
    """大引の下に床束(ハイブリッドシンボル)を配置する floor_post 命令を組み立てる。

    IFC に床束が無いため、大引(``CLASS_OOBIKI``)の平面芯線に沿って 910mm 間隔で
    床束を並べる。座標は通り芯・横架材と同じグリッド中心オフセットで補正する。
    高さの基準(基礎底盤上端)は配置先レイヤ ``F-床束`` のストーリレベルが担うため
    命令には高さ情報を持たせない。基礎が無いモデルでは空リストを返す。
    """
    if not has_foundation(ifc_file):
        return []

    _, center_x, center_y = resolve_lines(ifc_file)

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

        # 平面芯線(始点・終点)。傾斜大引でも平面投影の芯線に沿って並べる。
        sx = ox - center_x
        sy = oy - center_y
        ex = sx + ax * length
        ey = sy + ay * length
        span = math.hypot(ex - sx, ey - sy)
        if span <= 0.0:
            continue
        ux, uy = (ex - sx) / span, (ey - sy) / span

        for distance in _post_offsets(span):
            commands.append({
                'layer': LAYER_FOUNDATION_FLOOR_POST,
                'symbol': SYMBOL_FLOOR_POST,
                'position': [sx + ux * distance, sy + uy * distance],
            })
    return commands
