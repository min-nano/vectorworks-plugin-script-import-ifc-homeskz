"""柱 (IfcColumn) の解析と column 命令の組み立て。vs 非依存。

IFC の IfcColumn を走査し、span(またぐレベル区間)ごとの専用レイヤ
(``{from}to{to}-柱``)に配置する column 命令を生成する。span の ``from`` は柱が立つ
床レベル(1 始まり・GL=0)、``to`` は上端が届く床/母屋レベル(``resolve_column_to_level``。
管柱=次階の整数、小屋束・屋根束=屋根面で止まる +0.5、通し柱=複数階ぶん上)。各伏図は
その切断レベルを span が含むレイヤだけを表示するため、下屋の小屋束が上階の小屋伏図に
写り込まない。柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描くため、
断面寸法(幅・成)と柱高さを押し出しソリッドから取得する。構造用途は管柱・
通し柱は柱、小屋束は小屋束を設定する(小屋束を柱用途にすると VW の柱高さ
モデルで上端高さが崩れるため)。

**柱・小屋束の上下端高さは横架材天端(最上階は軒高)のストーリレベルにバインド
する**(梁と同じ仕組み)。柱(管柱・通し柱)は下端を当階の横架材天端、上端を上階
(次階)の横架材天端にバインドし、小屋束は下端・上端とも当階の横架材天端に
バインドする。``offset`` はバインド先レベルの絶対 Z から実際の下端/上端の絶対 Z
までの距離で、下端 Z(``elevation`` = ストーリ高さ + ローカル配置 Z の絶対値)と
柱高さ(``height``)から算出する。

**VW の構造材ツールは上下端 story bound の offset 差(top − bottom)をパス由来の
部材長に加算する。** 柱は上端を上階にバインドし offset 差が ≈0 になるため二重加算は
生じないが、小屋束(上階が無く上下端とも当階の横架材天端にバインドする)で上端 offset
を天端相当(bottom + height)にすると柱高さが二重加算され上端が約 2 倍になる。そこで
**小屋束は上端 offset を下端と同値にして加算分を 0 にし**、上端高さはパス(下端 +
height)に委ねる。描画フェーズはパスを絶対 Z に配置してから ``SetObjectStoryBound``
で上下端をこのレベル・オフセットにバインドし、編集時に高さがレイヤ基準へリセットされる
のを防ぐ。

**小屋束の断面寸法はホームズ君 IFC では適当な値なので、直上に乗る横架材
(母屋・棟木・登り梁)の断面幅に合わせた正方形に置き換える**(90mm 幅の母屋なら
90mm 角、105mm 幅なら 105mm 角)。``_member_width_on_top`` が小屋束の平面位置・
上端の絶対 Z を横架材命令と突き合わせ、footprint が小屋束を覆いかつ小屋束上端が
その材の Z 範囲に収まる母屋・棟木・登り梁の幅を返す。上に乗る材が見つからない
小屋束は IFC の断面をそのまま使う。

構造材 ID (member_id) は ``{幅}×{成} - {種別}`` に柱頭・柱脚金物の仕様を連結
した文字列にする(小屋束は上記の補正後の寸法で作る)。構造材ツールには金物専用
フィールドが無いため、金物仕様は MemberID に含めて保持する(梁の構造材 ID と
同じ扱い)。

柱頭・柱脚金物はホームズ君 IFC では柱と同じストーリに含まれる
IfcMechanicalFastener(柱頭/柱脚付近の立方体)として表現される。柱と同じ
平面座標に配置されるため XY 位置で柱と対応付け、金物の型
(IfcMechanicalFastenerType)の名前を**加工せずそのまま**仕様文字列として
命令の top_hardware / bottom_hardware に格納する。ホームズ君側で金物定義を
カスタマイズしている場合、型名が想定形式とは限らないため、現状はコロン分割
等の加工を行わず型名全体を登録する。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..document import ColumnCommand, MemberCommand, StoryBoundCommand
from .grid import resolve_lines
from .member import _get_profile_dims, build_member_commands
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_EAVES,
    get_local_placement_z,
    layer_prefix_for,
    parse_span_layer,
    resolve_beam_top_offset,
    span_layer_name,
)
from .structural_class import (
    CLASS_KOYAZUKA,
    CLASS_MOYA,
    CLASS_MUNAGI,
    CLASS_NOBORIBARI,
    resolve_column_class,
)

# 構造材ツールの構造用途 (StructuralUse) 値(VW の構造用途プルダウンの並び順に
# 対応する: <自動>, 梁="1", 桁, 根太, 柱="4", 小屋束="5", ...)。管柱・通し柱は
# 柱、小屋束は小屋束を設定する。小屋束を柱用途で描くと VW が柱の高さモデルを
# 適用して上端の高さオフセットと部材長が矛盾し上端高さが正しく描画されないため、
# 小屋束は小屋束用途にして実ジオメトリどおりの高さで描く。
STRUCTURAL_USE_COLUMN = '4'    # 柱
STRUCTURAL_USE_KOYAZUKA = '5'  # 小屋束

# 小屋束の断面幅を「上に乗る横架材」に合わせるための設定。ホームズ君 IFC が
# 出力する小屋束の断面寸法は当てにならない(適当な値)ため、描画する断面は実際に
# 直上に乗る材の断面幅に合わせた正方形にする(90mm 幅の母屋なら 90mm 角、105mm 幅
# なら 105mm 角)。上に乗り得る材は小屋組の上端材(母屋・棟木・登り梁)。
_KOYAZUKA_TOP_MEMBER_CLASSES = (CLASS_MOYA, CLASS_MUNAGI, CLASS_NOBORIBARI)
# 小屋束の平面位置が上端材の footprint に収まると認める許容値 (mm)。小屋束は材の
# 直下に立つため直交距離はほぼ 0 だが、モデリング誤差・傾斜梁の天端中央線ずれを吸収する。
_KOYAZUKA_MATCH_PERP_TOL = 40.0
# 上端材の軸方向の範囲判定の余裕 (mm)。棟束等は材の端(棟)に立つため端まで許容する。
_KOYAZUKA_MATCH_ALONG_TOL = 50.0
# 小屋束上端が上端材の Z 範囲(下端〜天端)に収まると認める余裕 (mm)。材が小屋束に
# 乗る(下端=上端)場合も貫く(小屋束が材天端付近まで伸びる棟束等)場合も拾う。
_KOYAZUKA_MATCH_Z_TOL = 30.0


def _member_width_on_top(
    px: float, py: float, top_abs: float,
    members: list[MemberCommand],
) -> float | None:
    """小屋束の直上に乗る横架材(母屋・棟木・登り梁)の断面幅を返す。見つからねば None。

    小屋束の平面位置 ``(px, py)``(グリッド中心オフセット済み)と上端の絶対 Z
    ``top_abs`` を横架材の member 命令と突き合わせ、①平面 footprint が小屋束を覆い
    (中心線からの直交距離が半幅以内)、②小屋束上端がその材の Z 範囲(下端〜天端)に
    収まる母屋・棟木・登り梁を探す。②は材が小屋束に乗る(材下端≈小屋束上端)場合も、
    小屋束が材を貫いて天端付近まで伸びる(棟束等)場合も拾う。最も小屋束上端に近い
    (小屋束が直接受ける)材の幅を返す。傾斜梁(登り梁)は天端 Z が軸方向に変化するため
    小屋束位置で補間する。

    ホームズ君 IFC が出力する小屋束の断面寸法は適当な値なので、描画する断面は実際に
    上に乗る材の断面幅に合わせた正方形にする(呼び出し側で width=depth に設定する)。
    """
    best: tuple[float, float, float] | None = None  # (|材下端−小屋束上端|, perp, width)
    for m in members:
        if m['class'] not in _KOYAZUKA_TOP_MEMBER_CLASSES:
            continue
        sx, sy = m['start']
        ex, ey = m['end']
        dx, dy = ex - sx, ey - sy
        length = math.hypot(dx, dy)
        if length <= 0.0:
            continue
        ux, uy = dx / length, dy / length
        t = (px - sx) * ux + (py - sy) * uy
        if not (-_KOYAZUKA_MATCH_ALONG_TOL <= t
                <= length + _KOYAZUKA_MATCH_ALONG_TOL):
            continue
        perp = abs((px - sx) * (-uy) + (py - sy) * ux)
        if perp > m['width'] / 2.0 + _KOYAZUKA_MATCH_PERP_TOL:
            continue
        # 傾斜梁は天端 Z が軸方向に変化するため小屋束位置の t で補間する
        frac = min(1.0, max(0.0, t / length))
        member_top = m['elevation'] + frac * (m['end_elevation'] - m['elevation'])
        member_bottom = member_top - m['height']
        if not (member_bottom - _KOYAZUKA_MATCH_Z_TOL
                <= top_abs <= member_top + _KOYAZUKA_MATCH_Z_TOL):
            continue
        key = (abs(member_bottom - top_abs), perp, m['width'])
        if best is None or key < best:
            best = key
    return best[2] if best is not None else None


# 柱が上階の床(次階 FL)を貫いていれば通し柱とみなす許容値 (mm)。管柱の上端は
# 次階の横架材天端(=次階 FL より梁背分下)で止まるため、次階 FL をわずかに超えた
# だけで通し柱と判定する。通し柱は実際にはほぼ 1 階分高いので余裕は小さくてよい。
THROUGH_COLUMN_TOL = 100.0


def is_through_column(top_abs: float, next_floor_elevation: float | None) -> bool:
    """柱の上端が上階の床(次階 FL)を貫いていれば通し柱(True)とみなす。

    next_floor_elevation が None(上階が無い最上階)のときは常に False。
    """
    if next_floor_elevation is None:
        return False
    return top_abs > next_floor_elevation + THROUGH_COLUMN_TOL


# span の to レベル判定の許容値 (mm)。柱上端が上階の横架材下端に達したかの判定に使う。
SPAN_LEVEL_TOL = 1.0


def resolve_column_to_level(
    base_index: int, top_abs: float,
    beam_bottoms: list[float], beam_tops: list[float],
) -> float:
    """柱上端が届く span の ``to`` レベル(1 始まり)を求める。

    ``base_index`` は 0 起点のストーリ番号で、柱の下端はその階の床(span では
    ``base_index + 1``)にある。上端 ``top_abs`` を base より上の各階の横架材(床梁)の
    **下端**(``beam_bottoms``)と比べ、達した最上の階(``reached``)を求める:

    - どの上階の横架材にも達しない(＝上端が直上階の梁下端未満) → その階には載らない
      屋根束扱いで **from + 0.5**(下屋の小屋束・棟束・主屋根の小屋束等)。管柱は必ず
      直上階の床梁下端に達するのでこの分岐には来ない。
    - 直上階の床梁下端に達すれば **from + 1**(管柱)。さらに上の階の床梁下端まで
      達すれば通し柱として到達した階まで伸ばす(1・2 階通し柱なら 3 階床＝from + 2)。

    横架材の天端ではなく**下端**を境界にするのは、通常の管柱が横架材天端ではなく
    下端まで(＝梁を下から受ける高さ)しか来ないため。天端を境界にすると、ホームズ君の
    モデルで天端付近まで伸びた管柱を貫き(通し)と誤判定してしまう。

    ただし**到達した最上階の横架材天端(最上階は軒高)より上端が高い柱**は、その階の
    床/軒に下から受けられる管柱・通し柱ではなく、屋根面で止まる**屋根束**なので
    **reached + 1 + 0.5** の半整数レベルにする(``beam_tops``＝各階の横架材天端の
    絶対 Z)。これがないと、例えば軒高より高く突き出す小屋束が屋根軒高の梁下端に達した
    だけで管柱扱いになり、``1to2.5`` に振り分けるべき柱が ``1to2`` になってしまう。
    管柱・通し柱の上端は受ける梁の下端(＝横架材天端より梁背ぶん下)に止まるため
    天端を超えず、この分岐には来ない。
    """
    reached = base_index  # 到達した最上階(0 起点)。初期値は自階=どの上階にも未到達
    for s in range(base_index + 1, len(beam_bottoms)):
        if top_abs >= beam_bottoms[s] - SPAN_LEVEL_TOL:
            reached = s
        else:
            break
    if reached == base_index or top_abs > beam_tops[reached] + SPAN_LEVEL_TOL:
        # 直上階の横架材にも達しない、または到達階の横架材天端(軒高)を超えて
        # 突き出す屋根束(小屋束等) → 到達階 +0.5 の半整数レベル
        return float(reached + 1) + 0.5
    return float(reached + 1)


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


def build_column_commands(
    ifc_file: ifcopenshell.file,
    members: list[MemberCommand] | None = None,
) -> list[ColumnCommand]:
    """IFC の柱から column 命令のリストを組み立てる。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。柱は span(またぐ
    レベル区間)ごとの専用レイヤ ``{from}to{to}-柱`` に配置し、梁と同じ構造材ツールで
    鉛直材として描く。span の ``from`` は柱が立つ床レベル(1 始まり)、``to`` は上端が
    届く床/母屋レベル(``resolve_column_to_level``。管柱=次階の整数、小屋束・屋根束=
    屋根面で止まる +0.5、通し柱=複数階ぶん上)。to レベルの判定には上の各階の横架材
    (床梁)の下端が要るため ``members`` を渡す(未指定なら内部で組み立てる。母屋は
    含めず横架材天端/軒高レイヤの梁だけを境界にする)。

    下端 Z(``elevation``)はストーリ高さ + ローカル配置 Z の絶対値、上端は下端 +
    柱高さ(``height``)。上下端高さは横架材天端(最上階は軒高)のストーリレベルに
    バインドする(``bottom_bound`` / ``top_bound``。柱は当階と上階、小屋束は当階の
    横架材天端)。

    小屋束の断面(``width`` / ``depth``)はホームズ君 IFC の値が適当なので、直上に
    乗る横架材(母屋・棟木・登り梁)の断面幅に合わせた正方形に置き換える
    (``_member_width_on_top``。母屋・棟木・登り梁の判定に横架材命令が要るため
    ``members`` を使う)。上に乗る材が見つからない小屋束は IFC の断面のまま。

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
    # 各階の横架材天端(最上階は軒高)の絶対 Z。柱の上下端をこの高さにバインドする。
    beam_top_abs = [
        elevations[i] if i == top_idx
        else elevations[i] + resolve_beam_top_offset(s)
        for i, s in enumerate(storeys)
    ]
    # 各階の横架材(床梁)下端の最小値。span の to レベル判定の境界に使う
    # (母屋 n-母屋 は含めず、横架材天端/軒高レイヤの床梁のみ)。梁が無い階は天端で代用。
    if members is None:
        members = build_member_commands(ifc_file)
    beam_bottoms: list[float] = []
    for i in range(len(storeys)):
        is_top = i == top_idx
        beam_layer = f'{layer_prefix_for(i, is_top)}-{LEVEL_EAVES if is_top else LEVEL_BEAM_TOP}'
        bottoms = [
            min(m['elevation'], m['end_elevation']) - m['height']
            for m in members if m['layer'] == beam_layer
        ]
        beam_bottoms.append(min(bottoms) if bottoms else beam_top_abs[i])

    commands: list[ColumnCommand] = []

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)

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

                px = ox - center_x
                py = oy - center_y

                # span(またぐレベル区間)ごとの専用レイヤに配置する。
                to_level = resolve_column_to_level(
                    i, top_abs, beam_bottoms, beam_top_abs)
                layer_name = span_layer_name(i + 1, to_level)

                # クラスは小屋束(IFC 記録)/通し柱・管柱(上下端の高さ)で判別する。
                next_floor_elevation = (
                    None if is_top else elevations[i + 1])
                through = is_through_column(top_abs, next_floor_elevation)
                column_class = resolve_column_class(
                    element.ObjectType, element.Name, i, top_idx, through)
                # 小屋束は構造用途を小屋束にする(柱用途だと VW の柱高さモデルで
                # 上端高さが崩れる)。
                is_koyazuka = column_class == CLASS_KOYAZUKA
                structural_use = (
                    STRUCTURAL_USE_KOYAZUKA
                    if is_koyazuka
                    else STRUCTURAL_USE_COLUMN)

                # ホームズ君 IFC の小屋束の断面寸法は適当な値なので、直上に乗る横架材
                # (母屋・棟木・登り梁)の断面幅に合わせた正方形に置き換える(90mm 幅の
                # 母屋なら 90mm 角、105mm 幅なら 105mm 角)。上に乗る材が見つからない
                # 小屋束は IFC の断面をそのまま使う。member_id もこの補正後の寸法で作る。
                if is_koyazuka:
                    on_top_width = _member_width_on_top(px, py, top_abs, members)
                    if on_top_width is not None:
                        width = depth = on_top_width

                column_type = resolve_column_type(element.ObjectType)
                member_id = make_column_member_id(
                    width, depth, column_type, top_hardware, bottom_hardware)

                # 上下端高さを横架材天端(最上階は軒高)のストーリレベルにバインドする。
                # 下端は当階の横架材天端、上端は柱(管柱・通し柱)なら上階(次階)の
                # 横架材天端、小屋束(上階が無い)なら当階の横架材天端にバインドし、
                # offset はバインド先レベルの絶対 Z から実際の下端/上端 Z までの距離。
                current_level = LEVEL_EAVES if is_top else LEVEL_BEAM_TOP
                current_top_abs = beam_top_abs[i]
                bottom_offset = bottom_abs - current_top_abs
                bottom_bound: StoryBoundCommand = {
                    'story_offset': 0, 'level': current_level,
                    'offset': bottom_offset}
                if is_koyazuka or is_top:
                    # 小屋束(および上階の無い最上階の柱)は上下端とも当階の横架材天端に
                    # バインドする。**上端の offset は下端と同値にする**: VW の構造材ツールは
                    # 上下端 story bound の offset 差(top − bottom)をパス由来の部材長に
                    # 加算するため、パスが既に柱高さ(height)を持つ小屋束で上端 offset を
                    # 天端相当(bottom + height)にすると柱高さが二重に加算され上端が約 2 倍に
                    # なる。offset 差を 0 にすれば加算分が消え、上端高さはパス(下端 + height)
                    # が担う。柱(管柱・通し柱)は上端を上階にバインドし offset 差が ≈0 に
                    # なるため二重加算が生じない。
                    top_bound: StoryBoundCommand = {
                        'story_offset': 0, 'level': current_level,
                        'offset': bottom_offset}
                else:
                    # 柱(管柱・通し柱)は上端を上階(次階)の横架材天端にバインドする。
                    next_is_top = (i + 1 == top_idx)
                    next_level = LEVEL_EAVES if next_is_top else LEVEL_BEAM_TOP
                    top_bound = {
                        'story_offset': 1, 'level': next_level,
                        'offset': top_abs - beam_top_abs[i + 1]}

                commands.append({
                    'layer': layer_name,
                    'member_id': member_id,
                    'class': column_class,
                    'structural_use': structural_use,
                    'position': [px, py],
                    'width': width,
                    'depth': depth,
                    'height': height,
                    'elevation': bottom_abs,
                    'top_hardware': top_hardware,
                    'bottom_hardware': bottom_hardware,
                    'bottom_bound': bottom_bound,
                    'top_bound': top_bound,
                })

    return commands


def collect_column_spans(
    columns: list[ColumnCommand],
) -> list[tuple[float, float, str]]:
    """column 命令から実在する span 柱レイヤを ``(from, to, layer)`` で列挙する。

    重複を除き ``(from, to)`` 昇順に並べた決定的なリストを返す。伏図(``sheet``)が
    切断レベルで表示レイヤを絞るのに使う。
    """
    seen: dict[str, tuple[float, float]] = {}
    for command in columns:
        parsed = parse_span_layer(command['layer'])
        if parsed is not None:
            seen[command['layer']] = parsed
    return sorted(
        ((frm, to, layer) for layer, (frm, to) in seen.items()),
        key=lambda item: (item[0], item[1]),
    )


def collect_column_layers_by_story(
    columns: list[ColumnCommand],
) -> dict[int, list[str]]:
    """span 柱レイヤを base ストーリ(0 起点 index = ``from`` - 1)ごとにまとめる。

    各ストーリのレイヤは ``(from, to)`` 昇順。story 命令が各ストーリに span レイヤの
    レベルを作るのに使う。
    """
    result: dict[int, list[str]] = {}
    for frm, _to, layer in collect_column_spans(columns):
        result.setdefault(int(frm) - 1, []).append(layer)
    return result
