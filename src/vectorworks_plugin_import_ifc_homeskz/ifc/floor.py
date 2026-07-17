"""床板 (IfcSlab "床版") の解析と floor 命令の組み立て。vs 非依存。

ホームズ君 IFC では床板は ``Name`` が ``床版`` の ``IfcSlab`` として表現される
(鉛直押し出しで、押し出しプロファイルがそのまま床の平面外形になる)。各床版が
属する階(FL ストーリ)の FL レイヤ(``n-FL``)に床ツール(Floor オブジェクト)で
描くための floor 命令を組み立てる。

要件:

- **床のある場所は IFC から抽出する** — ``床版`` の平面外形を床の外形にする。
- **厚みは 24mm 固定** — IFC の押し出し厚(実際には 28mm 等)は使わず 24mm にする。
- **高さは IFC の床位置を尊重する(段差=スキップフロアを表現する)** — 床下端の
  絶対 Z を IFC の床版ソリッドの最下端(``storey.Elevation`` + ローカル最下端 Z)
  そのままにする。標準の床高(横架材天端 = ストーリ高さ + ``resolve_beam_top_offset``)
  に一致する床は差分 0、段差のある床(スキップフロア)や床高の異なる床は横架材天端
  からの差分(ホームズ君で入力した基準高さからの高低差)ぶんずれた絶対 Z になる。
  高さ基準は標準の床高=横架材天端レベルにバインドし、その差分を ``bound.offset``
  で表す(段差はこの offset に現れる)。

平面外形の取得(``_world_solid`` / ``_footprint``)・押し出しソリッドの
ワールド変換・最下端 Z の取得(``_z_top_and_thickness``)は基礎(``ifc/footing.py``)
の低レベルヘルパーを再利用する(アンカーボルトが ``ifc/column.py`` の private
ヘルパーを再利用するのと同じパターン)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import FloorCommand, StoryBoundCommand
from .footing import _footprint, _world_solid, _z_top_and_thickness
from .grid import resolve_lines
from .story import (
    LEVEL_BEAM_TOP,
    LEVEL_FL,
    layer_prefix_for,
    resolve_beam_top_offset,
)
from .structural_class import CLASS_FLOOR

if TYPE_CHECKING:
    import ifcopenshell

# 床板を識別する IfcSlab の Name。
FLOOR_SLAB_NAME = '床版'
# 床厚 (mm)。要件により 24mm 固定(IFC の押し出し厚は使わない)。
FLOOR_THICKNESS = 24.0


def _is_floor_slab(element: ifcopenshell.entity_instance) -> bool:
    """要素が床板(``IfcSlab`` かつ ``Name`` が ``床版``)か判定する。"""
    return element.is_a('IfcSlab') and (element.Name or '') == FLOOR_SLAB_NAME


def build_floor_commands(ifc_file: ifcopenshell.file) -> list[FloorCommand]:
    """IFC の床板(``床版``)から floor 命令のリストを組み立てる。

    FL ストーリ(名前が ``FL`` で終わる ``IfcBuildingStorey``)を Elevation 昇順に
    走査し、各階の ``ContainsElements`` から床板(``床版``)を集めて、その階の
    FL レイヤ(``n-FL``)に配置する floor 命令にする。最上階(屋根)は FL レイヤを
    持たない(軒高のみ)ため対象外にする(床板は屋根には無い)。

    座標は通り芯・基礎と同じグリッド中心オフセットで補正する。**床下端の絶対 Z は
    IFC の床版ソリッドの最下端(``storey.Elevation`` + ローカル最下端 Z)をそのまま
    使い、IFC の床位置を尊重する**(段差=スキップフロアや床高の異なる床を表現する)。
    高さ基準は標準の床高=横架材天端レベル(``storey.Elevation +
    resolve_beam_top_offset(storey)``)にバインドし、床下端と横架材天端の差分
    (ホームズ君で入力した基準高さからの高低差)を ``bound.offset`` に格納する
    (床下端が横架材天端ちょうどの床は offset 0、段差のある床は offset がずれる)。
    厚みは 24mm 固定。
    """
    storeys = sorted(
        [s for s in ifc_file.by_type('IfcBuildingStorey')
         if (s.Name or '').upper().endswith('FL')],
        key=lambda s: float(s.Elevation or 0.0),
    )
    if not storeys:
        return []

    _, center_x, center_y = resolve_lines(ifc_file)

    top_idx = len(storeys) - 1
    commands: list[FloorCommand] = []
    for i, storey in enumerate(storeys):
        # 最上階(屋根)は FL レイヤを持たないため床板を配置しない。
        if i == top_idx:
            continue
        prefix = layer_prefix_for(i, is_top=False)
        layer_name = f'{prefix}-{LEVEL_FL}'
        storey_elevation = float(storey.Elevation or 0.0)
        # 標準の床高 = 横架材天端(基準高さ)。段差のある床はここからの高低差でずれる。
        beam_top_abs = storey_elevation + resolve_beam_top_offset(storey)

        for rel in storey.ContainsElements or ():
            for element in rel.RelatedElements:
                if not _is_floor_slab(element):
                    continue
                solid = _world_solid(element)
                if solid is None:
                    continue
                boundary = [[x - center_x, y - center_y]
                            for x, y in _footprint(solid)]
                # IFC の床位置を尊重する: 床下端の絶対 Z は床版ソリッドの最下端
                # (storey.Elevation + ローカル最下端 Z)をそのまま使う。標準の床高
                # (横架材天端)からの高低差は bound.offset に表れる(段差=スキップ
                # フロアはこの offset で表現される)。
                top_local, thickness_local = _z_top_and_thickness(solid)
                bottom_abs = storey_elevation + (top_local - thickness_local)
                bound: StoryBoundCommand = {
                    'story_offset': 0, 'level': LEVEL_BEAM_TOP,
                    'offset': bottom_abs - beam_top_abs}
                commands.append({
                    'layer': layer_name,
                    'class': CLASS_FLOOR,
                    'boundary': boundary,
                    'thickness': FLOOR_THICKNESS,
                    'elevation': bottom_abs,
                    'bound': bound,
                })
    return commands
