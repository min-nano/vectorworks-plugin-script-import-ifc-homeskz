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
                object_type: str | None = None,
                name: str | None = None) -> ifcopenshell.entity_instance:
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
        'IfcColumn', Name=name, ObjectPlacement=local_placement, Representation=prod_def,
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
        # 柱は span レイヤ ``{from}to{to}-柱`` に配置する。base(1 階=1 始まりレベル 1)
        # 起点なので from=1(``1to...``)。
        assert all(c['layer'].startswith('1to') and c['layer'].endswith('-柱')
                   for c in commands)
        # 構造材 ID は "{幅}×{成} - {種別}"(金物なし)
        assert all(c['member_id'] == '105×105 - 管柱' for c in commands)

    def test_top_story_uses_column_layer(self) -> None:
        """最上階の柱(小屋束等)も span レイヤに配置する(base = その階のレベル)。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 1
        # 単一ストーリ=レベル 1(1 始まり)。上に階が無いため屋根束扱いで 1to1.5。
        assert commands[0]['layer'] == '1to1.5-柱'
        # 下端高さ = ストーリ高さ + ローカル Z
        assert commands[0]['elevation'] == pytest.approx(6200.0)

    def test_column_binds_bottom_current_top_upper_floor(self) -> None:
        """柱(管柱・通し柱)は下端を当階、上端を上階の横架材天端にバインドする。

        offset はバインド先レベルの絶対 Z から実際の下端/上端 Z までの距離。
        当階(1FL)の横架材天端 = 600 + resolve_beam_top_offset、上階(2FL)の
        横架材天端 = 3500 + resolve_beam_top_offset。この IFC では柱以外に
        負の配置 Z を持つ要素が無いため beam_top_offset は 0(横架材天端 = FL 高さ)。
        """
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0, height=2718.0)

        command = build_column_commands(ifc)[0]
        # 下端=自階高さ+ローカル Z(600+0)、上端は elevation + height
        assert command['elevation'] == pytest.approx(600.0)
        assert command['height'] == pytest.approx(2718.0)
        # 下端は当階(story_offset=0)の横架材天端、offset = 600 - 600 = 0
        bottom = command['bottom_bound']
        assert bottom['story_offset'] == 0
        assert bottom['level'] == '横架材天端'
        assert bottom['offset'] == pytest.approx(0.0)
        # 上端は上階(story_offset=1)の横架材天端、offset = (600+2718) - 3500
        top = command['top_bound']
        assert top['story_offset'] == 1
        assert top['level'] == '横架材天端'
        assert top['offset'] == pytest.approx(600.0 + 2718.0 - 3500.0)

    def test_koyazuka_binds_both_ends_to_current_eaves(self) -> None:
        """小屋束は下端・上端とも当階の横架材天端(最上階は軒高)にバインドする。

        VW の構造材ツールは上下端 story bound の offset 差をパス由来の部材長に
        加算するため、パスが既に柱高さを持つ小屋束では上端 offset を下端と同値に
        して加算分を 0 にする(異なると柱高さが二重加算され上端が約 2 倍になる)。
        上端の実高さはパス(下端 + height)が担う。
        """
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 600.0)
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0, height=800.0,
                    object_type='STANDCOLUMN')

        command = build_column_commands(ifc)[0]
        # 最上階の柱(小屋束)は軒高(offset 0)を横架材天端の高さとする。
        # 下端 = 6300 - 100 = 6200、上端はパスの下端 + height = 7000。
        bottom = command['bottom_bound']
        top = command['top_bound']
        assert bottom['story_offset'] == 0
        assert bottom['level'] == '軒高'
        assert bottom['offset'] == pytest.approx(-100.0)
        # 上端 offset は下端と同値(offset 差 0 で二重加算を避ける)
        assert top['story_offset'] == 0
        assert top['level'] == '軒高'
        assert top['offset'] == pytest.approx(-100.0)

    def test_assigns_layer_per_story(self) -> None:
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        s2 = make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0)
        make_column(ifc, s2, 0.0, 0.0)

        layers = [c['layer'] for c in build_column_commands(ifc)]
        # 柱は span レイヤに配置する。1 階起点の柱は from=1(``1to...``)、2 階起点は
        # from=2(``2to...``)。
        assert any(lyr.startswith('1to') for lyr in layers)
        assert any(lyr.startswith('2to') for lyr in layers)

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

    def test_standcolumn_class_is_koyazuka(self) -> None:
        """ObjectType=STANDCOLUMN の柱は小屋束クラスになる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-05小屋組-02小屋束'

    def test_koyazuka_structural_use_is_koyazuka(self) -> None:
        """小屋束(最上階の柱)の構造用途は小屋束 "5" になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['structural_use'] == '5'

    def test_general_column_structural_use_is_column(self) -> None:
        """一般階の柱(管柱・通し柱)の構造用途は柱 "4" になる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0)

        commands = build_column_commands(ifc)
        assert commands[0]['structural_use'] == '4'

    def test_single_story_column_class_is_kudabashira(self) -> None:
        """1 階分で止まる一般階の柱は管柱クラスになる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 上端 ≈ 600 + 2844 = 3444 < 2FL(3500) → 管柱
        make_column(ifc, s1, 0.0, 0.0, height=2844.0)

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-03柱-02管柱'

    def test_through_column_class_is_toshibashira(self) -> None:
        """上階の床を貫く(複数階を通す)柱は通し柱クラスになる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 上端 ≈ 600 + 5700 = 6300 で 2FL(3500) を貫く → 通し柱
        make_column(ifc, s1, 0.0, 0.0, height=5700.0)

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-03柱-01通し柱'

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
