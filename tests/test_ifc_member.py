"""IFC 解析フェーズ (ifc.member) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.ifc.member import (
    _get_material_name,
    _get_placement_2d,
    _get_profile_dims,
    build_member_commands,
    make_member_id,
)


# ---------------------------------------------------------------------------
# テスト用 IFC エンティティ生成ヘルパー
# ---------------------------------------------------------------------------

def make_storey(ifc: ifcopenshell.file, name: str, elevation: float) -> ifcopenshell.entity_instance:
    """テスト用 IfcBuildingStorey を生成する。"""
    return ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)


def make_beam(ifc: ifcopenshell.file, storey: ifcopenshell.entity_instance,
              ox: float, oy: float, dx: float = 1.0, dy: float = 0.0,
              width: float = 120.0, height: float = 180.0, length: float = 3000.0,
              material_name: str = '', oz: float = 0.0) -> ifcopenshell.entity_instance:
    """テスト用 IfcBeam を生成して storey に追加する。

    Parameters
    ----------
    ox, oy   : ビーム始端の XY 座標 (mm)
    dx, dy   : ビーム軸方向の成分 (ビーム局所 X 方向)
    width    : IfcRectangleProfileDef.XDim (幅, mm)
    height   : IfcRectangleProfileDef.YDim (背, mm)
    length   : IfcExtrudedAreaSolid.Depth (長さ, mm)
    oz       : ビームのローカル配置 Z 座標 (mm, ストーリ FL からの相対)
    """
    # 配置（梁の延伸方向 = ローカル Z = Axis 属性）
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    axis = ifc.create_entity('IfcDirection', DirectionRatios=[dx, dy, 0.0])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    # プロファイルと押し出しソリッド
    profile = ifc.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA', XDim=float(width), YDim=float(height)
    )
    extrude_dir = ifc.create_entity('IfcDirection', DirectionRatios=[1.0, 0.0, 0.0])
    solid = ifc.create_entity(
        'IfcExtrudedAreaSolid', SweptArea=profile, ExtrudedDirection=extrude_dir, Depth=float(length)
    )

    # 表現コンテキストとシェイプ表現
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

    beam = ifc.create_entity(
        'IfcBeam', ObjectPlacement=local_placement, Representation=prod_def
    )

    # 材料関連付け
    if material_name:
        mat = ifc.create_entity('IfcMaterial', Name=material_name)
        ifc.create_entity('IfcRelAssociatesMaterial', RelatedObjects=[beam], RelatingMaterial=mat)

    # ストーリへの所属
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[beam]
    )
    return beam


def make_grid_axis(ifc: ifcopenshell.file, name: str,
                   x1: float, y1: float, x2: float, y2: float) -> None:
    """テスト用 IfcGridAxis を生成する（グリッド中心算出に使用）。"""
    pts = [
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x1, y1]),
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x2, y2]),
    ]
    polyline = ifc.create_entity('IfcPolyline', Points=pts)
    ifc.create_entity('IfcGridAxis', AxisTag=name, AxisCurve=polyline, SameSense=True)


# ---------------------------------------------------------------------------
# _get_placement_2d
# ---------------------------------------------------------------------------

class TestGetPlacement2D:
    def test_extracts_origin(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_2d(beam)
        assert result is not None
        ox, oy, dx, dy = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)

    def test_defaults_direction_to_x_axis_when_no_axis(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_2d(beam)
        assert result is not None
        ox, oy, dx, dy = result
        assert dx == pytest.approx(1.0)
        assert dy == pytest.approx(0.0)

    def test_extracts_axis_direction(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[0.0, 1.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_2d(beam)
        assert result is not None
        ox, oy, dx, dy = result
        assert dx == pytest.approx(0.0)
        assert dy == pytest.approx(1.0)

    def test_normalizes_direction(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        # 長さ 2 のベクトル
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[2.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_2d(beam)
        assert result is not None
        ox, oy, dx, dy = result
        assert math.hypot(dx, dy) == pytest.approx(1.0)

    def test_returns_none_when_no_placement(self) -> None:
        elem = MagicMock()
        elem.ObjectPlacement = None
        assert _get_placement_2d(elem) is None

    def test_returns_none_for_non_local_placement(self) -> None:
        placement = MagicMock()
        placement.is_a = lambda t: False
        elem = MagicMock()
        elem.ObjectPlacement = placement
        assert _get_placement_2d(elem) is None


# ---------------------------------------------------------------------------
# _get_profile_dims
# ---------------------------------------------------------------------------

class TestGetProfileDims:
    def _make_element(self, width: float, height: float, length: float,
                      rep_id: str = 'Body') -> MagicMock:
        profile = MagicMock()
        profile.is_a = lambda t: t == 'IfcRectangleProfileDef'
        profile.XDim = float(width)
        profile.YDim = float(height)

        solid = MagicMock()
        solid.is_a = lambda t: t == 'IfcExtrudedAreaSolid'
        solid.SweptArea = profile
        solid.Depth = float(length)

        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = rep_id
        shape_rep.Items = [solid]

        rep = MagicMock()
        rep.Representations = [shape_rep]

        elem = MagicMock()
        elem.Representation = rep
        return elem

    def test_extracts_width_height_length(self) -> None:
        elem = self._make_element(120.0, 180.0, 3000.0)
        assert _get_profile_dims(elem) == (120.0, 180.0, 3000.0)

    def test_returns_none_when_no_representation(self) -> None:
        elem = MagicMock()
        elem.Representation = None
        assert _get_profile_dims(elem) is None

    def test_skips_non_body_representation(self) -> None:
        elem = self._make_element(120.0, 180.0, 3000.0, rep_id='Axis')
        assert _get_profile_dims(elem) is None

    def test_skips_non_rectangle_profile(self) -> None:
        profile = MagicMock()
        profile.is_a = lambda t: False  # IfcRectangleProfileDef でない

        solid = MagicMock()
        solid.is_a = lambda t: t == 'IfcExtrudedAreaSolid'
        solid.SweptArea = profile

        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = 'Body'
        shape_rep.Items = [solid]

        rep = MagicMock()
        rep.Representations = [shape_rep]
        elem = MagicMock()
        elem.Representation = rep
        assert _get_profile_dims(elem) is None


# ---------------------------------------------------------------------------
# _get_material_name
# ---------------------------------------------------------------------------

class TestGetMaterialName:
    def test_extracts_ifc_material_name(self) -> None:
        mat = MagicMock()
        mat.is_a = lambda t: t == 'IfcMaterial'
        mat.Name = '杉対称異等級集成材E105-F355'

        rel = MagicMock()
        rel.is_a = lambda t: t == 'IfcRelAssociatesMaterial'
        rel.RelatingMaterial = mat

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == '杉対称異等級集成材E105-F355'

    def test_extracts_first_material_from_material_list(self) -> None:
        mat0 = MagicMock()
        mat0.Name = '1 番目の材種'
        mat_list = MagicMock()
        mat_list.is_a = lambda t: t == 'IfcMaterialList'
        mat_list.Materials = [mat0]

        rel = MagicMock()
        rel.is_a = lambda t: t == 'IfcRelAssociatesMaterial'
        rel.RelatingMaterial = mat_list

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == '1 番目の材種'

    def test_returns_empty_when_no_association(self) -> None:
        elem = MagicMock()
        elem.HasAssociations = []
        assert _get_material_name(elem) == ''

    def test_skips_non_material_relations(self) -> None:
        rel = MagicMock()
        rel.is_a = lambda t: False  # IfcRelAssociatesMaterial でない

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == ''


# ---------------------------------------------------------------------------
# make_member_id
# ---------------------------------------------------------------------------

class TestMakeMemberId:
    def test_with_material(self) -> None:
        assert make_member_id(120, 180, '杉対称異等級集成材E105-F355') == \
            '120×180 - 杉対称異等級集成材E105-F355'

    def test_without_material(self) -> None:
        assert make_member_id(120, 180, '') == '120×180'

    def test_rounds_float_dimensions(self) -> None:
        assert make_member_id(120.4, 179.6, '') == '120×180'


# ---------------------------------------------------------------------------
# build_member_commands
# ---------------------------------------------------------------------------

class TestBuildMemberCommands:
    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_member_commands(ifcopenshell.file()) == []

    def test_builds_command_per_beam(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_beam(ifc, storey, 0.0, 0.0)
        make_beam(ifc, storey, 0.0, 1000.0)
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 2
        assert all(c['layer'] == '1-横架材天端' for c in commands)

    def test_top_story_uses_eaves_layer(self) -> None:
        """最上階 (RFL) のビームは R-軒高レイヤを指定する。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['layer'] == 'R-軒高'
        # 最上階の配置高さはストーリ高さそのもの
        assert commands[0]['elevation'] == pytest.approx(5973.0)

    def test_assigns_layer_per_story(self) -> None:
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 473.0)
        s2 = make_storey(ifc, '2FL', 3273.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, s1, 0.0, 0.0)
        make_beam(ifc, s2, 0.0, 0.0)

        layers = [c['layer'] for c in build_member_commands(ifc)]
        assert '1-横架材天端' in layers
        assert '2-横架材天端' in layers

    def test_applies_grid_center_offset(self) -> None:
        """グリッド中心オフセットを引いた座標で命令を組み立てることを確認する。"""
        ifc = ifcopenshell.file()
        # グリッド軸: X=0〜2000, Y=0〜2000 → center=(1000, 1000)
        make_grid_axis(ifc, 'X1', 0.0, 0.0, 2000.0, 0.0)
        make_grid_axis(ifc, 'Y1', 0.0, 0.0, 0.0, 2000.0)
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # ビーム始端 (1500, 1500): センタリング後 → (500, 500)
        # 長さ 600, X 方向 → 終端 (1100, 500)
        make_beam(ifc, storey, 1500.0, 1500.0, dx=1.0, dy=0.0, length=600.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        command = commands[0]
        assert command['start'] == [pytest.approx(500.0), pytest.approx(500.0)]
        assert command['end'] == [pytest.approx(1100.0), pytest.approx(500.0)]
        # layer_elevation = storey.Elevation + resolve_beam_top_offset = 473 + 0 = 473
        assert command['elevation'] == pytest.approx(473.0)

    def test_uses_beam_local_z_for_elevation(self) -> None:
        """各横架材は自身のローカル配置 Z で絶対高さに描画される。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # ローカル Z = -250 の梁: 絶対高さ = 473 + (-250) = 223
        make_beam(ifc, storey, 0.0, 0.0, oz=-250.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['elevation'] == pytest.approx(223.0)

    def test_beams_at_different_heights_get_distinct_elevations(self) -> None:
        """基準高さにない横架材も含め、各梁が固有の高さに配置される。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, oz=-48.0)
        make_beam(ifc, storey, 0.0, 1000.0, oz=-300.0)

        elevations = sorted(c['elevation'] for c in build_member_commands(ifc))
        assert elevations[0] == pytest.approx(173.0)   # 473 - 300
        assert elevations[1] == pytest.approx(425.0)   # 473 - 48

    def test_falls_back_to_layer_elevation_when_local_z_unavailable(self) -> None:
        """ローカル Z を取得できない梁はレイヤ基準高さ（横架材天端）にフォールバックする。

        配置 Coordinates が 2 要素だと get_local_placement_z() は None を返すが、
        _get_placement_2d() は XY を取得できるため命令自体は生成される。
        このときレイヤ基準高さ（ストーリ高さ + resolve_beam_top_offset）を使う。
        オフセットを 0 でない値にして、ストーリ高さそのものではなくレイヤ基準高さが
        使われることを検証する。
        """
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # 床版 (Z=-50) を置き resolve_beam_top_offset を -50 にする
        slab_pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, -50.0])
        slab_ap = ifc.create_entity('IfcAxis2Placement3D', Location=slab_pt)
        slab_lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=slab_ap)
        slab = ifc.create_entity('IfcSlab', ObjectPlacement=slab_lp)
        ifc.create_entity(
            'IfcRelContainedInSpatialStructure',
            RelatingStructure=storey, RelatedElements=[slab],
        )
        # 梁の配置 Z を欠落させ get_local_placement_z() を None にする
        beam = make_beam(ifc, storey, 0.0, 0.0)
        beam.ObjectPlacement.RelativePlacement.Location.Coordinates = [0.0, 0.0]

        commands = build_member_commands(ifc)
        member_cmds = [c for c in commands if c['member_id'] == '120×180']
        assert len(member_cmds) == 1
        # layer_elevation = 473 + (-50) = 423（ストーリ高さ 473 ではない）
        assert member_cmds[0]['elevation'] == pytest.approx(423.0)

    def test_sets_member_id_and_dimensions(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, width=120.0, height=180.0, length=3000.0,
                  material_name='杉対称異等級集成材E105-F355')

        commands = build_member_commands(ifc)
        assert commands[0]['member_id'] == '120×180 - 杉対称異等級集成材E105-F355'
        assert commands[0]['width'] == pytest.approx(120.0)
        assert commands[0]['height'] == pytest.approx(180.0)

    def test_skips_beam_without_placement(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        beam = ifc.create_entity('IfcBeam')  # 配置・ジオメトリなし
        ifc.create_entity(
            'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[beam]
        )

        assert build_member_commands(ifc) == []

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, material_name='杉')

        commands = build_member_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
