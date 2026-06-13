"""柱 (IfcColumn) の解析と column 命令の組み立て。vs 非依存。

IFC の IfcColumn を走査し、各階の横架材天端レイヤ(最上階は軒高レイヤ)に
配置する column 命令を生成する。断面寸法(幅・成)と柱高さは押し出しソリッド
から取得し、配置 Z はストーリ高さに柱のローカル配置 Z を加えた絶対値を使う。

柱頭・柱脚金物はホームズ君 IFC では柱と同じストーリに含まれる
IfcMechanicalFastener(柱頭/柱脚付近の立方体)として表現される。柱と同じ
平面座標に配置されるため XY 位置で柱と対応付け、金物の型
(IfcMechanicalFastenerType)の名前(例: ``柱頭金物:(ろ)``)から仕様文字列を
取り出して命令の top_hardware / bottom_hardware に格納する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnCommand, StoryBound
from .grid import resolve_lines
from .member import _get_profile_dims
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_COLUMN,
    LEVEL_COLUMN_PLAN,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
    resolve_beam_top_offset,
)

if TYPE_CHECKING:
    import ifcopenshell

# IfcColumn.ObjectType から木造BIM 柱・間柱ツールの種別名へのマッピング。
# ホームズ君 IFC では ObjectType は None(管柱)または "STANDCOLUMN"(小屋束)。
# ツールの種別ドロップダウンの有効値は 管柱 / 通し柱 / 間柱 / 小屋束 / 吊木。
DEFAULT_COLUMN_TYPE = '管柱'
COLUMN_TYPE_BY_OBJECT_TYPE = {
    'STANDCOLUMN': '小屋束',
}

# 柱頭・柱脚金物 (IfcMechanicalFastener) を識別する名前キーワード
HARDWARE_TOP_KEYWORD = '柱頭金物'
HARDWARE_BOTTOM_KEYWORD = '柱脚金物'
# 金物の型名から仕様を切り出す区切り文字 (例: '柱頭金物:(ろ)' → '(ろ)')
_HARDWARE_SPEC_SEPARATOR = ':'


def _position_key(ox: float, oy: float) -> tuple[float, float]:
    """金物と柱を対応付ける XY 位置キー(浮動小数の丸め込み付き)。"""
    return (round(ox, 3), round(oy, 3))


def _get_fastener_type_name(
    fastener: ifcopenshell.entity_instance,
) -> str | None:
    """IfcMechanicalFastener の型 (IfcMechanicalFastenerType) 名を返す。

    型は IfcRelDefinesByType 経由で辿る。逆方向属性名がスキーマで異なる
    (IFC2X3=IsDefinedBy / IFC4=IsTypedBy)ため両方を走査する。
    型が無い場合は None を返す。
    """
    for attr in ('IsTypedBy', 'IsDefinedBy'):
        for rel in getattr(fastener, attr, None) or ():
            if rel.is_a('IfcRelDefinesByType'):
                relating_type = rel.RelatingType
                if relating_type is not None:
                    return relating_type.Name
    return None


def _hardware_spec(type_name: str | None) -> str:
    """金物の型名から仕様文字列を取り出す (例: '柱頭金物:(ろ)' → '(ろ)')。

    区切り文字が無ければ型名全体を仕様とみなす。型名が無ければ空文字を返す。
    """
    if not type_name:
        return ''
    if _HARDWARE_SPEC_SEPARATOR in type_name:
        return type_name.split(_HARDWARE_SPEC_SEPARATOR, 1)[1]
    return type_name


def _collect_column_hardware(
    storey: ifcopenshell.entity_instance,
) -> tuple[dict[tuple[float, float], str], dict[tuple[float, float], str]]:
    """ストーリ内の柱頭・柱脚金物を XY 位置で索引する。

    柱頭・柱脚金物は柱と同じストーリに含まれ、柱と同じ平面座標に立方体として
    配置される。金物の仕様は型名のコロン以降に入っている。

    Returns: (heads, bases) — XY 位置キー → 仕様文字列 の辞書。
        heads は柱頭金物、bases は柱脚金物。
    """
    heads: dict[tuple[float, float], str] = {}
    bases: dict[tuple[float, float], str] = {}
    for rel in storey.ContainsElements or ():
        for element in rel.RelatedElements:
            if not element.is_a('IfcMechanicalFastener'):
                continue
            name = element.Name or ''
            if HARDWARE_TOP_KEYWORD in name:
                target = heads
            elif HARDWARE_BOTTOM_KEYWORD in name:
                target = bases
            else:
                continue
            position = _get_position_2d(element)
            if position is None:
                continue
            spec = _hardware_spec(_get_fastener_type_name(element))
            if not spec:
                continue
            target.setdefault(_position_key(*position), spec)
    return heads, bases


def resolve_column_type(object_type: str | None) -> str:
    """IfcColumn.ObjectType を柱・間柱ツールの種別名に変換する。

    未知の ObjectType(None 含む)は既定種別(管柱)として扱う。
    """
    if object_type is None:
        return DEFAULT_COLUMN_TYPE
    return COLUMN_TYPE_BY_OBJECT_TYPE.get(object_type, DEFAULT_COLUMN_TYPE)


def _get_position_2d(
    element: ifcopenshell.entity_instance,
) -> tuple[float, float] | None:
    """IfcProduct のローカル配置から 2D 配置座標 (ox, oy) を返す。

    取得できない場合は None を返す。ホームズ君 IFC ではストーリの XY 原点が
    (0, 0) のため、ローカル配置 Location の XY をそのまま平面座標として扱える
    (横架材と同じ座標系・グリッド中心オフセットで補正できる)。
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
    if len(coords) < 2:
        return None
    return float(coords[0]), float(coords[1])


def _base_level(
    index: int, top_idx: int, elevations: list[float], beam_offsets: list[float],
) -> tuple[str, float]:
    """階 index の「基準レベル」(柱を配置するレイヤのレベル) を返す。

    Returns: (level_type, base_absolute)
        一般階は横架材天端 (FL からの負オフセット)、最上階は軒高 (オフセット 0)。
        base_absolute はそのレベルの絶対 Z (= storey_elevation + base_offset)。
    """
    if index == top_idx:
        return LEVEL_EAVES, elevations[index]
    return LEVEL_BEAM_TOP, elevations[index] + beam_offsets[index]


def build_column_commands(ifc_file: ifcopenshell.file) -> list[ColumnCommand]:
    """IFC の柱から column 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    柱は各階の柱レイヤ(``n-柱``)に配置し、柱・間柱ツールの伏図記号は
    伏図レイヤ(``n-柱(伏図)``)に描く。高さ基準(横架材天端／軒高)は
    レベルタイプとして引き続き参照する。

    柱高さは固定値ではなく上下端をストーリレベル基準で指定する
    (高さ基準(下)=当該階の横架材天端、高さ基準(上)=上階の横架材天端 or 軒高)。
    オフセットは IFC 上の絶対高さに合わせ、階高変更に追従できるようにする。
    最上階(上階が存在しない)の柱は上下端とも当該階の軒高を基準にする。

    柱頭・柱脚金物 (IfcMechanicalFastener) は柱と同じ平面座標に配置されるため
    XY 位置で柱と対応付け、金物の仕様文字列を top_hardware / bottom_hardware に
    格納する(該当金物が無ければ空文字)。
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
    elevations = [float(s.Elevation or 0.0) for s in storeys]
    beam_offsets = [resolve_beam_top_offset(s) for s in storeys]

    commands: list[ColumnCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 柱は各階の柱レイヤに配置し、伏図記号は伏図レイヤに描く
        layer_name = f'{prefix}-{LEVEL_COLUMN}'
        plan_layer_name = f'{prefix}-{LEVEL_COLUMN_PLAN}'

        storey_elevation = elevations[i]
        base_level_type, base_abs = _base_level(
            i, top_idx, elevations, beam_offsets)

        # 柱頭・柱脚金物を XY 位置で索引し、各柱と対応付ける
        head_hardware, base_hardware = _collect_column_hardware(storey)

        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not element.is_a('IfcColumn'):
                    continue

                position = _get_position_2d(element)
                if position is None:
                    continue
                dims = _get_profile_dims(element)
                if dims is None:
                    continue

                ox, oy = position
                # 押し出し: XDim=幅, YDim=成, Depth=柱高さ
                width, depth, height = dims

                # 柱頭・柱脚金物を同一平面座標から対応付ける(無ければ空文字)
                hardware_key = _position_key(ox, oy)
                top_hardware = head_hardware.get(hardware_key, '')
                bottom_hardware = base_hardware.get(hardware_key, '')

                local_z = get_local_placement_z(element) or 0.0
                bottom_abs = storey_elevation + local_z
                top_abs = bottom_abs + height

                # 高さ基準(下): 当該階の基準レベル (横架材天端 or 軒高)
                bottom_bound: StoryBound = {
                    'story': 0,
                    'level': base_level_type,
                    'offset': bottom_abs - base_abs,
                }

                # 高さ基準(上): 上階の横架材天端 or 軒高。上階が無ければ当該階の軒高。
                if i < top_idx:
                    upper = i + 1
                    if upper == top_idx:
                        upper_level_type, upper_abs = LEVEL_EAVES, elevations[upper]
                    else:
                        upper_level_type = LEVEL_BEAM_TOP
                        upper_abs = elevations[upper] + beam_offsets[upper]
                    top_bound: StoryBound = {
                        'story': 1,
                        'level': upper_level_type,
                        'offset': top_abs - upper_abs,
                    }
                else:
                    top_bound = {
                        'story': 0,
                        'level': LEVEL_EAVES,
                        'offset': top_abs - base_abs,
                    }

                commands.append({
                    'layer': layer_name,
                    'plan_layer': plan_layer_name,
                    'column_type': resolve_column_type(element.ObjectType),
                    'position': [ox - center_x, oy - center_y],
                    'width': width,
                    'depth': depth,
                    'height': height,
                    'elevation': bottom_abs,
                    'bottom_bound': bottom_bound,
                    'top_bound': top_bound,
                    'top_hardware': top_hardware,
                    'bottom_hardware': bottom_hardware,
                })

    return commands
