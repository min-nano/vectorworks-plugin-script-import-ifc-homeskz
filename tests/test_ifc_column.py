"""IFC 解析フェーズ (ifc.column) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.ifc.column import (
    _get_position_2d,
    _hardware_spec,
    build_column_commands,
    make_column_member_id,
    resolve_column_type,
    resolve_height_bounds,
)


# ---------------------------------------------------------------------------
# テスト用 IFC エンティティ生成ヘルパー
# ---------------------------------------------------------------------------

def make_storey(ifc: ifcopenshell.file, name: str, elevation: float) -> ifcopenshell.entity_instance:
    """テスト用 IfcBuildingStorey を生成する。"""
    return ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)


def make_column(ifc: ifcopenshell.file, storey: ifcopenshell.entity_instance,
                ox: float, oy: float, oz: float = 0.0,
                width: float = 105.0, depth: float = 105.0, height: float = 2844.0,
                object_type: str | None = None) -> ifcopenshell.entity_instance:
    """テスト用 IfcColumn を生成して storey に追加する。

    Parameters
    ----------
    ox, oy, oz : 柱のローカル配置座標 (mm)。oz はストーリ原点からの相対 Z(負値)。
    width      : IfcRectangleProfileDef.XDim (断面幅, mm)
    depth      : IfcRectangleProfileDef.YDim (断面成, mm)
    height     : IfcExtrudedAreaSolid.Depth (柱高さ, mm)
    """
    # 配置(柱はローカル Z 方向に押し出される)
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    # プロファイルと押し出しソリッド(押し出し方向 = ローカル Z)
    profile = ifc.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA', XDim=float(width), YDim=float(depth)
    )
    extrude_dir = ifc.create_entity('IfcDirection', DirectionRatios=[0.0, 0.0, 1.0])
    solid = ifc.create_entity(
        'IfcExtrudedAreaSolid', SweptArea=profile, ExtrudedDirection=extrude_dir, Depth=float(height)
    )

    wcs_pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
    wcs = ifc.create_entity('IfcAxis2Placement3D', Location=wcs_pt)
    ctx = ifc.create_entity(
        'IfcGeometricRepresentationContext', CoordinateSpaceDimension=3, WorldCoordinateSystem=wcs
    )
    shape_rep = ifc.create_entity(
        'IfcShapeRepresentation',
        ContextOfItems=ctx,
        RepresentationIdentifier='Body',
        RepresentationType='SweptSolid',
        Items=[solid],
    )
    prod_def = ifc.create_entity('IfcProductDefinitionShape', Representations=[shape_rep])

    column = ifc.create_entity(
        'IfcColumn', ObjectPlacement=local_placement, Representation=prod_def,
        ObjectType=object_type,
    )

    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[column]
    )
    return column


def make_hardware(ifc: ifcopenshell.file, storey: ifcopenshell.entity_instance,
                  ox: float, oy: float, name: str, type_name: str,
                  oz: float = 0.0) -> ifcopenshell.entity_instance:
    """テスト用 柱頭/柱脚金物 (IfcMechanicalFastener) を生成して storey に追加する。

    name に ``柱頭金物`` / ``柱脚金物`` を含めると柱頭/柱脚として分類される。
    type_name は金物の型名(例: ``柱頭金物:(ろ)``)で、加工せずそのまま仕様になる。
    """
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    fastener = ifc.create_entity(
        'IfcMechanicalFastener', Name=name, ObjectPlacement=local_placement
    )
    fastener_type = ifc.create_entity('IfcMechanicalFastenerType', Name=type_name)
    ifc.create_entity(
        'IfcRelDefinesByType', RelatedObjects=[fastener], RelatingType=fastener_type
    )
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey,
        RelatedElements=[fastener],
    )
    return fastener


def make_grid_axis(ifc: ifcopenshell.file, name: str,
                   x1: float, y1: float, x2: float, y2: float) -> None:
    """テスト用 IfcGridAxis を生成する(グリッド中心算出に使用)。"""
    pts = [
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x1, y1]),
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x2, y2]),
    ]
    polyline = ifc.create_entity('IfcPolyline', Points=pts)
    ifc.create_entity('IfcGridAxis', AxisTag=name, AxisCurve=polyline, SameSense=True)


# ---------------------------------------------------------------------------
# _get_position_2d
# ---------------------------------------------------------------------------

class TestGetPosition2D:
    def test_extracts_origin(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0, -174.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        col = ifc.create_entity('IfcColumn', ObjectPlacement=lp)

        result = _get_position_2d(col)
        assert result is not None
        ox, oy = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)

    def test_returns_none_when_no_placement(self) -> None:
        ifc = ifcopenshell.file()
        col = ifc.create_entity('IfcColumn')
        assert _get_position_2d(col) is None


# ---------------------------------------------------------------------------
# resolve_column_type
# ---------------------------------------------------------------------------

class TestResolveColumnType:
    def test_none_maps_to_kudabashira(self) -> None:
        assert resolve_column_type(None) == '管柱'

    def test_standcolumn_maps_to_koyazuka(self) -> None:
        assert resolve_column_type('STANDCOLUMN') == '小屋束'

    def test_unknown_falls_back_to_default(self) -> None:
        assert resolve_column_type('SOMETHING_ELSE') == '管柱'


# ---------------------------------------------------------------------------
# _hardware_spec
# ---------------------------------------------------------------------------

class TestHardwareSpec:
    def test_returns_type_name_unprocessed(self) -> None:
        """型名は加工せず(コロン分割せず)そのまま仕様文字列になる。"""
        assert _hardware_spec('柱頭金物:(ろ)') == '柱頭金物:(ろ)'
        assert _hardware_spec('柱脚金物:C12') == '柱脚金物:C12'

    def test_returns_whole_name_without_separator(self) -> None:
        assert _hardware_spec('HD-B20') == 'HD-B20'

    def test_returns_empty_for_none_or_empty(self) -> None:
        assert _hardware_spec(None) == ''
        assert _hardware_spec('') == ''


# ---------------------------------------------------------------------------
# make_column_member_id
# ---------------------------------------------------------------------------

class TestMakeColumnMemberId:
    def test_section_and_type_without_hardware(self) -> None:
        assert make_column_member_id(105, 105, '管柱', '', '') == '105×105 - 管柱'

    def test_rounds_dimensions(self) -> None:
        assert make_column_member_id(104.6, 120.4, '管柱', '', '') == '105×120 - 管柱'

    def test_appends_both_hardware(self) -> None:
        assert make_column_member_id(
            105, 105, '管柱', '柱頭金物:(ろ)', '柱脚金物:(い)'
        ) == '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'

    def test_appends_only_present_hardware(self) -> None:
        assert make_column_member_id(
            105, 105, '小屋束', '柱頭金物:(ろ)', ''
        ) == '105×105 - 小屋束 / 柱頭金物:(ろ)'


# ---------------------------------------------------------------------------
# build_column_commands
# ---------------------------------------------------------------------------

class TestResolveHeightBounds:
    def test_general_story(self) -> None:
        # 階 0 / 全 3 階 (top=2): 始端=自階横架材天端、終端=上階横架材天端。
        # offset は実ジオメトリ(下端=自階天端、上端=上階天端から梁背分下)から決まる。
        # 下端 426 = 自階天端 → 始端 offset 0、上端 3270 = 上階天端 3452 − 梁背 182。
        start, end = resolve_height_bounds(
            0, 2, bottom_abs=426.0, top_abs=3270.0,
            current_level_z=426.0, upper_level_z=3452.0)
        assert start == {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0}
        assert end == {
            'story_offset': 1, 'level': '横架材天端', 'offset': pytest.approx(-182.0)}

    def test_story_just_below_top(self) -> None:
        # 階 1 / top=2: 上階が屋根のため終端=軒高。
        # 下端 3452 = 自階天端 → 始端 offset 0、上端 6118 = 軒高 6300 − 梁背 182。
        start, end = resolve_height_bounds(
            1, 2, bottom_abs=3452.0, top_abs=6118.0,
            current_level_z=3452.0, upper_level_z=6300.0)
        assert start == {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0}
        assert end == {
            'story_offset': 1, 'level': '軒高', 'offset': pytest.approx(-182.0)}

    def test_top_story(self) -> None:
        # 最上階: 始端・終端とも自階軒高。下端=軒高 → 始端 offset 0、終端は柱高さ分。
        start, end = resolve_height_bounds(
            2, 2, bottom_abs=6300.0, top_abs=7200.0,
            current_level_z=6300.0, upper_level_z=None)
        assert start == {'story_offset': 0, 'level': '軒高', 'offset': 0.0}
        assert end == {
            'story_offset': 0, 'level': '軒高', 'offset': pytest.approx(900.0)}


class TestBuildColumnCommands:
    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_column_commands(ifcopenshell.file()) == []

    def test_builds_command_per_column(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_column(ifc, storey, 0.0, 0.0)
        make_column(ifc, storey, 1000.0, 0.0)
        make_storey(ifc, 'RFL', 6300.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 2
        assert all(c['layer'] == '1-柱' for c in commands)
        # 構造材 ID は "{幅}×{成} - {種別}"(金物なし)
        assert all(c['member_id'] == '105×105 - 管柱' for c in commands)

    def test_top_story_uses_column_layer(self) -> None:
        """最上階 (RFL) の柱(小屋束等)は R-柱 レイヤに配置する。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['layer'] == 'R-柱'
        # 下端高さ = ストーリ高さ + ローカル Z
        assert commands[0]['elevation'] == pytest.approx(6200.0)

    def test_general_story_binds_to_beam_top_and_upper(self) -> None:
        """一般階の柱は始端=自階の横架材天端、終端=上階の横架材天端にバインドする。

        始端は柱下端が自階天端に一致するため offset 0、終端は柱上端が上階梁の
        下端(上階天端から梁背分下)になるため offset が負になる。
        """
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 下端=600(自階天端)、上端=600+2718=3318=上階天端3500−182(梁背)
        make_column(ifc, s1, 0.0, 0.0, height=2718.0)

        command = build_column_commands(ifc)[0]
        assert command['start_bound'] == {
            'story_offset': 0, 'level': '横架材天端', 'offset': pytest.approx(0.0)}
        assert command['end_bound'] == {
            'story_offset': 1, 'level': '横架材天端',
            'offset': pytest.approx(-182.0)}

    def test_story_below_top_binds_upper_to_eaves(self) -> None:
        """最上階直下の階は上階が屋根のため終端=軒高にバインドする。"""
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 600.0)
        s2 = make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 下端=3500(自階天端)、上端=3500+2618=6118=軒高6300−182(梁背)
        make_column(ifc, s2, 0.0, 0.0, height=2618.0)

        command = build_column_commands(ifc)[0]
        assert command['start_bound'] == {
            'story_offset': 0, 'level': '横架材天端', 'offset': pytest.approx(0.0)}
        assert command['end_bound'] == {
            'story_offset': 1, 'level': '軒高', 'offset': pytest.approx(-182.0)}

    def test_top_story_binds_both_ends_to_eaves(self) -> None:
        """最上階の柱は始端・終端とも自階の軒高基準で、終端は柱高さ分のオフセット。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, height=900.0)

        command = build_column_commands(ifc)[0]
        assert command['start_bound'] == {
            'story_offset': 0, 'level': '軒高', 'offset': 0.0}
        assert command['end_bound'] == {
            'story_offset': 0, 'level': '軒高', 'offset': pytest.approx(900.0)}

    def test_assigns_layer_per_story(self) -> None:
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        s2 = make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0)
        make_column(ifc, s2, 0.0, 0.0)

        layers = [c['layer'] for c in build_column_commands(ifc)]
        assert '1-柱' in layers
        assert '2-柱' in layers

    def test_elevation_is_story_plus_local_z(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-174.0)

        commands = build_column_commands(ifc)
        assert commands[0]['elevation'] == pytest.approx(426.0)

    def test_applies_grid_center_offset(self) -> None:
        """グリッド中心オフセットを引いた座標で命令を組み立てることを確認する。"""
        ifc = ifcopenshell.file()
        # グリッド軸: X=0〜2000, Y=0〜2000 → center=(1000, 1000)
        make_grid_axis(ifc, 'X1', 0.0, 0.0, 2000.0, 0.0)
        make_grid_axis(ifc, 'Y1', 0.0, 0.0, 0.0, 2000.0)
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 柱 (1500, 1500): センタリング後 → (500, 500)
        make_column(ifc, storey, 1500.0, 1500.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['position'] == [pytest.approx(500.0), pytest.approx(500.0)]

    def test_sets_dimensions(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, width=105.0, depth=120.0, height=2844.0)

        command = build_column_commands(ifc)[0]
        assert command['width'] == pytest.approx(105.0)
        assert command['depth'] == pytest.approx(120.0)
        assert command['height'] == pytest.approx(2844.0)

    def test_standcolumn_object_type_maps_to_koyazuka(self) -> None:
        """ObjectType=STANDCOLUMN は member_id の種別が小屋束になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['member_id'] == '105×105 - 小屋束'

    def test_skips_column_without_placement(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        column = ifc.create_entity('IfcColumn')  # 配置・ジオメトリなし
        ifc.create_entity(
            'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[column]
        )

        assert build_column_commands(ifc) == []

    def test_elevation_is_bottom_absolute_z(self) -> None:
        """下端 (elevation) は当該階の絶対 Z (ストーリ高さ + ローカル Z)。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0, oz=-174.0, height=2844.0)

        cmd = build_column_commands(ifc)[0]
        # 下端 = 600 - 174 = 426, 高さ = 2844 (上端は描画時に下端 + 高さ)
        assert cmd['elevation'] == pytest.approx(426.0)
        assert cmd['height'] == pytest.approx(2844.0)

    def test_hardware_defaults_to_empty_when_absent(self) -> None:
        """金物が無い柱は top_hardware / bottom_hardware が空文字になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == ''
        assert command['bottom_hardware'] == ''

    def test_matches_hardware_by_position(self) -> None:
        """同一平面座標の柱頭・柱脚金物の仕様を柱に対応付ける。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 1000.0, 2000.0)
        make_hardware(ifc, storey, 1000.0, 2000.0,
                      name='柱No.4:柱頭金物', type_name='柱頭金物:(ろ)', oz=2544.0)
        make_hardware(ifc, storey, 1000.0, 2000.0,
                      name='柱No.4:柱脚金物', type_name='柱脚金物:(い)', oz=-174.0)

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == '柱頭金物:(ろ)'
        assert command['bottom_hardware'] == '柱脚金物:(い)'
        # 金物仕様は member_id にも連結される
        assert command['member_id'] == \
            '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'

    def test_does_not_match_hardware_at_other_position(self) -> None:
        """別の平面座標の金物は対応付けない。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)
        make_hardware(ifc, storey, 5000.0, 5000.0,
                      name='柱No.9:柱頭金物', type_name='柱頭金物:(ろ)')

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == ''
        assert command['bottom_hardware'] == ''

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)

        commands = build_column_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
