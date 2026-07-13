"""アンカーボルト (IfcMechanicalFastener) の解析と anchor_bolt 命令の組み立て。vs 非依存。

ホームズ君 IFC ではアンカーボルトは IfcMechanicalFastener として表現され、型
(IfcMechanicalFastenerType)の名前がボルト本体か座金かを区別する:

- ボルト本体: 型名が ``アンカーボルト:{種別}:定着長さ:{長さ}mm`` (種別は Z1/Z2/座金なし)。
- 座金: 型名が ``アンカーボルト座金:{種別}`` (角座金。矩形断面)。

各アンカーボルトはボルト本体・座金の 2 要素で表されるため、**ボルト本体だけ**を
対象にする(座金は同一軸芯にあり、両方を数えると二重になる。座金なしのボルトは
座金要素が無いため、ボルト本体を採ればすべてのアンカーボルトを漏れなく数えられる)。

ボルト本体を **ハイブリッドシンボル** に置換する。ホームズ君 IFC のサンプルには
M12/M16 の直接表記が無く、代わりに Z1/Z2 の種別コード(角座金 Z1=40×40=M12、
Z2=60×60=M16 相当)と座金なしがある。判定方針は以下(要件どおり):

- 座金付き(Z1/Z2 等、型名が ``座金なし`` を含まない)→ ``アンカーボルト_M12``
- 座金なし(型名が ``座金なし`` を含む)→ ``アンカーボルト_M16``

2D 基準位置はボルト軸芯(ローカル配置 Location の XY を通り芯と同じグリッド中心
オフセットで補正)。高さの基準は基礎天端で、これは配置先レイヤ
(F-アンカーボルト)のストーリレベル(基礎天端)が担うため命令には持たせない。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import AnchorBoltCommand
from .column import _get_fastener_type_name, _get_position_2d
from .grid import resolve_lines
from .story import LAYER_FOUNDATION_ANCHOR

if TYPE_CHECKING:
    import ifcopenshell

# ボルト本体の型名接頭辞(座金 ``アンカーボルト座金:`` はこの接頭辞に一致しない)
_BOLT_TYPE_PREFIX = 'アンカーボルト:'
# 座金なしを表す型名中のトークン(座金付きと区別して M16 に振り分ける)
_WASHERLESS_TOKEN = '座金なし'

# 置換するハイブリッドシンボル名
SYMBOL_M12 = 'アンカーボルト_M12'  # 座金付き
SYMBOL_M16 = 'アンカーボルト_M16'  # 座金なし


def _is_anchor_bolt(type_name: str | None) -> bool:
    """型名がアンカーボルト本体(座金でない)を表すなら True。"""
    return type_name is not None and type_name.startswith(_BOLT_TYPE_PREFIX)


def resolve_anchor_bolt_symbol(type_name: str) -> str:
    """アンカーボルト本体の型名から置換するシンボル名を返す。

    型名が座金なし(``座金なし`` を含む)なら M16、そうでなければ M12。
    """
    if _WASHERLESS_TOKEN in type_name:
        return SYMBOL_M16
    return SYMBOL_M12


def build_anchor_bolt_commands(
    ifc_file: ifcopenshell.file,
) -> list[AnchorBoltCommand]:
    """IFC のアンカーボルトから anchor_bolt 命令のリストを組み立てる。

    IfcMechanicalFastener のうち型名がアンカーボルト本体のものを対象にし、
    軸芯 XY(通り芯と同じグリッド中心オフセットで補正)と置換シンボル名を
    命令に格納する。配置先レイヤは基礎ストーリの F-アンカーボルト。
    """
    _, center_x, center_y = resolve_lines(ifc_file)

    commands: list[AnchorBoltCommand] = []
    for element in ifc_file.by_type('IfcMechanicalFastener'):
        type_name = _get_fastener_type_name(element)
        if not _is_anchor_bolt(type_name):
            continue
        assert type_name is not None  # _is_anchor_bolt が保証する
        position = _get_position_2d(element)
        if position is None:
            continue
        ox, oy = position
        commands.append({
            'layer': LAYER_FOUNDATION_ANCHOR,
            'symbol': resolve_anchor_bolt_symbol(type_name),
            'position': [ox - center_x, oy - center_y],
        })
    return commands
