"""床束の解析と floor_post 命令の組み立て。vs 非依存。

ホームズ君 EX の IFC には**床束が出力されない**(オブジェクト・型・プロパティの
いずれにも床束・束の位置や仕様が現れない)。そのため床束は IFC から抽出できず、
要件どおり**大引の下に一定間隔(910mm)で決め打ち配置**する。

- 対象: ``Name`` の種別が ``大引``(``member_class_from_name`` が
  ``CLASS_OOBIKI`` を返す)の IfcBeam / IfcMember。
- 位置: 各大引の平面芯線に沿って、**始点(端部)から ``910mm`` ずつ**床束を並べる
  (``_post_offsets``)。始点から 910mm・1820mm・… の位置に床束を置き、最後の床束と
  終点(反対側の端部)との間隔は 910mm 未満の半端になってよい。端点そのものには
  床束を置かない(端部は土台・隣の大引・基礎が受ける)。芯線長が 910mm 以下の大引
  (単モジュール=805mm 等)は両端が 910mm 以内で受けられるため床束を置かない。
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

    始点(端部)から ``_POST_INTERVAL`` ずつ、``910mm``・``1820mm``・… の位置に
    床束を並べる。最後の床束と終点(反対側の端部)との間隔は 910mm 未満の半端に
    なってよい。端点そのものには床束を置かない(端部は土台・隣の大引・基礎が
    受ける)ため、終点ちょうど以遠には置かない。芯線長が 910mm 以下の大引は
    床束 0 本(両端が 910mm 以内で受けられる)。
    """
    if length <= 0.0:
        return []
    offsets: list[float] = []
    k = 1
    while _POST_INTERVAL * k < length:
        offsets.append(_POST_INTERVAL * k)
        k += 1
    return offsets


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
