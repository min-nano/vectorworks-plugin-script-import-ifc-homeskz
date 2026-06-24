"""柱 (IfcColumn) の解析と column 命令の組み立て。vs 非依存。

IFC の IfcColumn を走査し、各階の柱レイヤ(``n-柱``)に配置する column 命令を
生成する。柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描くため、
断面寸法(幅・成)と柱高さを押し出しソリッドから取得する。高さ基準は
ストーリレベルにバインドする(構造用途は柱):始端は自階の横架材天端、終端は
上階の横架材天端(最上階直下の階では上階=屋根のため軒高)。最上階(屋根)の柱は
上階が無いため始端・終端とも自階の軒高を基準にし、終端は柱高さ分持ち上げる。
下端 Z(ストーリ高さ + ローカル配置 Z の絶対値)と柱高さはパスのジオメトリに使う。

構造材 ID (member_id) は ``{幅}×{成} - {種別}`` に柱頭・柱脚金物の仕様を連結
した文字列にする。構造材ツールには金物専用フィールドが無いため、金物仕様は
MemberID に含めて保持する(梁の構造材 ID と同じ扱い)。

柱頭・柱脚金物はホームズ君 IFC では柱と同じストーリに含まれる
IfcMechanicalFastener(柱頭/柱脚付近の立方体)として表現される。柱と同じ
平面座標に配置されるため XY 位置で柱と対応付け、金物の型
(IfcMechanicalFastenerType)の名前を**加工せずそのまま**仕様文字列として
命令の top_hardware / bottom_hardware に格納する。ホームズ君側で金物定義を
カスタマイズしている場合、型名が想定形式とは限らないため、現状はコロン分割
等の加工を行わず型名全体を登録する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnCommand, StoryBoundCommand
from .grid import resolve_lines
from .member import _get_profile_dims
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_COLUMN,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
    resolve_beam_top_offset,
)

if TYPE_CHECKING:
    import ifcopenshell

# IfcColumn.ObjectType から柱種別名へのマッピング(構造材 ID の表記に使う)。
# ホームズ君 IFC では ObjectType は None(管柱)または "STANDCOLUMN"(小屋束)。
DEFAULT_COLUMN_TYPE = '管柱'
COLUMN_TYPE_BY_OBJECT_TYPE = {
    'STANDCOLUMN': '小屋束',
}

# 柱頭・柱脚金物 (IfcMechanicalFastener) を識別する名前キーワード
HARDWARE_TOP_KEYWORD = '柱頭金物'
HARDWARE_BOTTOM_KEYWORD = '柱脚金物'


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
    """金物の型名を加工せずそのまま仕様文字列として返す。

    ホームズ君側で金物定義をカスタマイズしている場合、型名が想定した
    ``柱頭金物:(ろ)`` 形式とは限らない。コロン分割等の加工で文字列が
    失われる(空欄になる)のを避けるため、現状は型名を加工せずそのまま
    登録する。型名が無ければ空文字を返す。
    """
    return type_name or ''


def _collect_column_hardware(
    storey: ifcopenshell.entity_instance,
) -> tuple[dict[tuple[float, float], str], dict[tuple[float, float], str]]:
    """ストーリ内の柱頭・柱脚金物を XY 位置で索引する。

    柱頭・柱脚金物は柱と同じストーリに含まれ、柱と同じ平面座標に立方体として
    配置される。金物の仕様(型名)は加工せずそのまま登録する。

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


def _beam_top_level_name(is_top: bool) -> str:
    """ストーリの横架材天端に相当するレベル名を返す。

    一般階は ``横架材天端``、最上階(屋根)は ``軒高``。
    """
    return LEVEL_EAVES if is_top else LEVEL_BEAM_TOP


def beam_top_abs_z(elevation: float, beam_offset: float, is_top: bool) -> float:
    """ストーリの横架材天端(最上階は軒高)の絶対 Z を返す。

    一般階は ``ストーリ高さ + 横架材天端オフセット(負値)``、最上階は軒高
    (オフセット 0)のため ``ストーリ高さ`` そのもの。
    """
    return elevation if is_top else elevation + beam_offset


def resolve_height_bounds(
    index: int, top_index: int,
    bottom_abs: float, top_abs: float,
    current_level_z: float, upper_level_z: float | None,
) -> tuple[StoryBoundCommand, StoryBoundCommand]:
    """柱の高さ基準(ストーリレベルへのバインド)を求める。

    構造用途は柱とし、柱頭/柱脚をストーリレベルにバインドする。各端の
    ``offset`` は**バインド先レベルの絶対 Z から柱端(絶対 Z)までの距離**で、
    柱の実ジオメトリ(IFC の下端 ``bottom_abs`` と上端 ``top_abs``)から決まる。
    こうすることで、ストーリ高さを VW 側で変更しても柱端はレベルから一定距離を
    保ち、かつインポート時点では IFC 通りの長さで描かれる。

    - 一般階: 始端=自階の横架材天端、終端=上階の横架材天端。最上階の直下の階は
      上階が屋根(横架材天端が無く軒高のみ)のため終端=軒高になる。標準的な柱
      では始端は横架材天端に一致し ``offset≈0``、終端は上階梁の下端(=上階
      横架材天端から梁背分下)になるため ``offset≈ -梁背`` になる。
    - 最上階(屋根): 上階が無いため始端・終端とも自階の軒高を基準にし、終端は
      軒高から柱高さ分(``top_abs - 軒高``)持ち上げる。

    Parameters
    ----------
    bottom_abs, top_abs : 柱下端・上端の絶対 Z(``top_abs = bottom_abs + 柱高さ``)。
    current_level_z     : 自階の横架材天端(最上階は軒高)の絶対 Z。
    upper_level_z       : 上階の横架材天端(屋根直下なら軒高)の絶対 Z。
                          最上階では上階が無いため None を渡す。

    Returns: (start_bound, end_bound)
    """
    is_top = index == top_index
    if is_top:
        start_bound: StoryBoundCommand = {
            'story_offset': 0, 'level': LEVEL_EAVES,
            'offset': bottom_abs - current_level_z}
        end_bound: StoryBoundCommand = {
            'story_offset': 0, 'level': LEVEL_EAVES,
            'offset': top_abs - current_level_z}
        return start_bound, end_bound
    upper_is_top = (index + 1) == top_index
    assert upper_level_z is not None
    start_bound = {
        'story_offset': 0, 'level': LEVEL_BEAM_TOP,
        'offset': bottom_abs - current_level_z}
    end_bound = {
        'story_offset': 1, 'level': _beam_top_level_name(upper_is_top),
        'offset': top_abs - upper_level_z}
    return start_bound, end_bound


def resolve_column_type(object_type: str | None) -> str:
    """IfcColumn.ObjectType を柱種別名に変換する。

    未知の ObjectType(None 含む)は既定種別(管柱)として扱う。
    """
    if object_type is None:
        return DEFAULT_COLUMN_TYPE
    return COLUMN_TYPE_BY_OBJECT_TYPE.get(object_type, DEFAULT_COLUMN_TYPE)


def make_column_member_id(
    width: float, depth: float, column_type: str,
    top_hardware: str, bottom_hardware: str,
) -> str:
    """柱の構造材 ID 文字列を生成する。

    ``{幅}×{成} - {種別}`` を基本とし、柱頭・柱脚金物の仕様(空でないもの)を
    `` / `` 区切りで連結する。構造材ツールには金物専用フィールドが無いため、
    金物仕様は MemberID に含めて保持する。金物の仕様文字列は型名そのまま
    (例: ``柱頭金物:(ろ)``)で自己記述的なので、そのまま連結する。

    例: make_column_member_id(105, 105, '管柱', '柱頭金物:(ろ)', '柱脚金物:(い)')
        → '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'
    """
    w = int(round(width))
    d = int(round(depth))
    member_id = f'{w}×{d} - {column_type}'
    parts = [hw for hw in (top_hardware, bottom_hardware) if hw]
    if parts:
        member_id = member_id + ' / ' + ' / '.join(parts)
    return member_id


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


def build_column_commands(ifc_file: ifcopenshell.file) -> list[ColumnCommand]:
    """IFC の柱から column 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    柱は各階の柱レイヤ(``n-柱``)に配置し、梁と同じ構造材ツールで鉛直材として
    描く。下端 Z(``elevation``)はストーリ高さ + ローカル配置 Z の絶対値、
    上端は下端 + 柱高さ(``height``)で、絶対 Z の固定パスとして描画する
    (ストーリレベルへの高さバインドは使わない)。

    構造材 ID(``member_id``)は ``{幅}×{成} - {種別}`` に柱頭・柱脚金物の仕様を
    連結した文字列。柱頭・柱脚金物 (IfcMechanicalFastener) は柱と同じ平面座標に
    配置されるため XY 位置で柱と対応付け、金物の仕様文字列を
    top_hardware / bottom_hardware に格納する(該当金物が無ければ空文字)。
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
    # 各階の横架材天端オフセット(story.py のレベル定義と同じ算出方法)。
    # 高さバインドの offset を実ジオメトリから求めるため絶対 Z 換算に使う。
    beam_offsets = [resolve_beam_top_offset(s) for s in storeys]

    commands: list[ColumnCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        # 柱は各階の柱レイヤに配置する
        layer_name = f'{prefix}-{LEVEL_COLUMN}'

        storey_elevation = elevations[i]

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

                column_type = resolve_column_type(element.ObjectType)
                member_id = make_column_member_id(
                    width, depth, column_type, top_hardware, bottom_hardware)

                # 高さバインドの基準となるレベルの絶対 Z(自階・上階)。
                current_level_z = beam_top_abs_z(
                    storey_elevation, beam_offsets[i], is_top)
                if is_top:
                    upper_level_z: float | None = None
                else:
                    upper_is_top = (i + 1) == top_idx
                    upper_level_z = beam_top_abs_z(
                        elevations[i + 1], beam_offsets[i + 1], upper_is_top)
                start_bound, end_bound = resolve_height_bounds(
                    i, top_idx, bottom_abs, top_abs,
                    current_level_z, upper_level_z)

                commands.append({
                    'layer': layer_name,
                    'member_id': member_id,
                    'position': [ox - center_x, oy - center_y],
                    'width': width,
                    'depth': depth,
                    'height': height,
                    'elevation': bottom_abs,
                    'start_bound': start_bound,
                    'end_bound': end_bound,
                    'top_hardware': top_hardware,
                    'bottom_hardware': bottom_hardware,
                })

    return commands
