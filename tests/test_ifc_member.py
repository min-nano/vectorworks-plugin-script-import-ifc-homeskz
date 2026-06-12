"""IFC 解析フェーズ (ifc.member) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.document import MemberCommand
from vectorworks_plugin_import_ifc_homeskz.ifc.member import (
    _get_material_name,
    _get_placement_3d,
    _get_profile_dims,
    build_member_commands,
    make_member_id,
    resolve_member_interferences,
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
              material_name: str = '', oz: float = 0.0,
              dz: float = 0.0) -> ifcopenshell.entity_instance:
    """テスト用 IfcBeam を生成して storey に追加する。

    Parameters
    ----------
    ox, oy   : ビーム始端の XY 座標 (mm)
    dx, dy   : ビーム軸方向の成分 (ビーム局所 X 方向)
    width    : IfcRectangleProfileDef.XDim (幅, mm)
    height   : IfcRectangleProfileDef.YDim (背, mm)
    length   : IfcExtrudedAreaSolid.Depth (長さ, mm)
    oz       : ビームのローカル配置 Z 座標 (mm, ストーリ FL からの相対)
    dz       : ビーム軸方向の Z 成分（登り梁・隅木等の傾斜梁用）
    """
    # 配置（梁の延伸方向 = ローカル Z = Axis 属性）
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    axis = ifc.create_entity('IfcDirection', DirectionRatios=[dx, dy, dz])
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
# _get_placement_3d
# ---------------------------------------------------------------------------

class TestGetPlacement3D:
    def test_extracts_origin(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0, -48.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        ox, oy, oz, _ax, _ay, _az = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)
        assert oz == pytest.approx(-48.0)

    def test_returns_none_z_when_coordinates_2d(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        assert result[2] is None

    def test_defaults_direction_to_x_axis_when_no_axis(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        _ox, _oy, _oz, ax, ay, az = result
        assert (ax, ay, az) == (pytest.approx(1.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_extracts_axis_direction(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[0.0, 1.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        _ox, _oy, _oz, ax, ay, az = result
        assert ax == pytest.approx(0.0)
        assert ay == pytest.approx(1.0)
        assert az == pytest.approx(0.0)

    def test_extracts_sloped_axis_z_component(self) -> None:
        """傾斜梁（隅木・登り梁等）の Axis Z 成分を保持する。"""
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[0.6, 0.0, 0.8])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        _ox, _oy, _oz, ax, ay, az = result
        assert ax == pytest.approx(0.6)
        assert ay == pytest.approx(0.0)
        assert az == pytest.approx(0.8)

    def test_normalizes_direction(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        # 長さ 2 のベクトル
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[2.0, 0.0, 2.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_3d(beam)
        assert result is not None
        _ox, _oy, _oz, ax, ay, az = result
        assert math.sqrt(ax * ax + ay * ay + az * az) == pytest.approx(1.0)

    def test_returns_none_when_no_placement(self) -> None:
        elem = MagicMock()
        elem.ObjectPlacement = None
        assert _get_placement_3d(elem) is None

    def test_returns_none_for_non_local_placement(self) -> None:
        placement = MagicMock()
        placement.is_a = lambda t: False
        elem = MagicMock()
        elem.ObjectPlacement = placement
        assert _get_placement_3d(elem) is None


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
        # 配置高さは天端 = ストーリ高さ + ローカル Z(0) + 背/2 (断面中心 → 天端補正)
        assert commands[0]['elevation'] == pytest.approx(5973.0 + 90.0)
        assert commands[0]['end_elevation'] == pytest.approx(5973.0 + 90.0)

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
        # 天端 = ストーリ高さ 473 + ローカル Z(0) + 背 180 の半分
        assert command['elevation'] == pytest.approx(563.0)

    def test_uses_beam_local_z_for_elevation(self) -> None:
        """各横架材は自身のローカル配置 Z（断面中心）から天端高さに描画される。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # ローカル Z = -250 (断面中心), 背 180: 天端 = 473 - 250 + 90 = 313
        make_beam(ifc, storey, 0.0, 0.0, oz=-250.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['elevation'] == pytest.approx(313.0)

    def test_elevation_is_section_top_not_center(self) -> None:
        """ホームズ君 IFC の配置 Z は断面中心なので、背/2 を足した天端を格納する。

        構造材ツールの断面基準点（左右中央・上端）にそのまま渡せる値にするため。
        """
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # 実データと同じ関係: 背 105 の梁が天端 -5 にある場合、中心 Z = -57.5
        make_beam(ifc, storey, 0.0, 0.0, height=105.0, oz=-57.5)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        # 天端 = 473 + (-57.5) + 105/2 = 468
        assert commands[0]['elevation'] == pytest.approx(468.0)
        assert commands[0]['end_elevation'] == pytest.approx(468.0)

    def test_beams_at_different_heights_get_distinct_elevations(self) -> None:
        """基準高さにない横架材も含め、各梁が固有の高さに配置される。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, oz=-48.0)
        make_beam(ifc, storey, 0.0, 1000.0, oz=-300.0)

        elevations = sorted(c['elevation'] for c in build_member_commands(ifc))
        assert elevations[0] == pytest.approx(263.0)   # 473 - 300 + 90
        assert elevations[1] == pytest.approx(515.0)   # 473 - 48 + 90

    def test_sloped_beam_keeps_slope_and_plan_projection(self) -> None:
        """傾斜梁（登り梁・隅木等）は始端・終端の天端 Z が異なる傾斜した命令になる。

        平面座標は軸の XY 成分 × 全長（平面投影長）で求め、
        天端中央線は断面中心線を軸直交方向に背/2 持ち上げた位置になる。
        """
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # 軸 (0.6, 0, 0.8), 全長 1000, 背 180
        make_beam(ifc, storey, 0.0, 0.0, dx=0.6, dy=0.0, dz=0.8,
                  height=180.0, length=1000.0)

        commands = build_member_commands(ifc)
        assert len(commands) == 1
        command = commands[0]
        # 軸直交・上向きの単位ベクトル n = (-0.8, 0, 0.6), 背/2 = 90
        # → 断面中心線から (-72, 0, +54) ずらした天端中央線
        assert command['start'] == [pytest.approx(-72.0), pytest.approx(0.0)]
        # 平面投影長 = 0.6 × 1000 = 600
        assert command['end'] == [pytest.approx(528.0), pytest.approx(0.0)]
        # 始端天端 = 473 + 0 + 54 = 527, 終端は 0.8 × 1000 = 800 上がる
        assert command['elevation'] == pytest.approx(527.0)
        assert command['end_elevation'] == pytest.approx(1327.0)

    def test_skips_vertical_axis_member(self) -> None:
        """軸が鉛直な材（横架材でない）は命令を生成しない。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, dx=0.0, dy=0.0, dz=1.0)

        assert build_member_commands(ifc) == []

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
        # layer_elevation = 473 + (-50) = 423（ストーリ高さ 473 ではない）。
        # レイヤ基準高さは既に天端なので背/2 の補正は掛からない
        assert member_cmds[0]['elevation'] == pytest.approx(423.0)
        assert member_cmds[0]['end_elevation'] == pytest.approx(423.0)

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

    def test_trims_interfering_beam_end(self) -> None:
        """T 字状に食い込む乙梁の端部が甲梁の面まで詰められる（build 経由）。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # 甲梁: Y 方向の通し材 (x=0, y=-1000〜1000), 幅 120 → 面は x=±60
        make_beam(ifc, storey, 0.0, -1000.0, dx=0.0, dy=1.0, width=120.0,
                  height=180.0, length=2000.0, material_name='甲')
        # 乙梁: X 方向, +x 側から甲の中心線 (x=0) まで食い込む
        make_beam(ifc, storey, 600.0, 500.0, dx=-1.0, dy=0.0, width=105.0,
                  height=180.0, length=600.0, material_name='乙')

        commands = build_member_commands(ifc)
        otsu = next(c for c in commands if c['member_id'].endswith('乙'))
        kou = next(c for c in commands if c['member_id'].endswith('甲'))
        # 乙の端部は甲の +x 面 (x=60) まで詰められる
        assert otsu['end'][0] == pytest.approx(60.0)
        assert otsu['end'][1] == pytest.approx(500.0)
        assert otsu['start'] == [pytest.approx(600.0), pytest.approx(500.0)]
        # 甲（通し材）は変更されない
        assert kou['start'] == [pytest.approx(0.0), pytest.approx(-1000.0)]
        assert kou['end'] == [pytest.approx(0.0), pytest.approx(1000.0)]


# ---------------------------------------------------------------------------
# resolve_member_interferences
# ---------------------------------------------------------------------------

def _member(start: list[float], end: list[float], width: float = 120.0,
            height: float = 180.0, elevation: float = 473.0,
            layer: str = '1-横架材天端', member_id: str = 'm',
            end_elevation: float | None = None) -> MemberCommand:
    return {
        'layer': layer, 'member_id': member_id,
        'start': start, 'end': end,
        'width': width, 'height': height, 'elevation': elevation,
        'end_elevation': elevation if end_elevation is None else end_elevation,
    }


class TestResolveMemberInterferences:
    def test_trims_t_joint_end_to_face(self) -> None:
        # 通し材: 幅 120 (面 x=±60), Y 方向 x=0
        primary = _member([0.0, -1000.0], [0.0, 1000.0], member_id='primary')
        # 食い込む材: +x から x=0 まで, 端点を x=60 (面) へ詰める
        butting = _member([600.0, 500.0], [0.0, 500.0], width=105.0, member_id='butting')

        result = resolve_member_interferences([primary, butting])
        prim, but = result[0], result[1]
        assert but['end'] == [pytest.approx(60.0), pytest.approx(500.0)]
        assert but['start'] == [pytest.approx(600.0), pytest.approx(500.0)]
        # 通し材は不変
        assert prim['start'] == [pytest.approx(0.0), pytest.approx(-1000.0)]
        assert prim['end'] == [pytest.approx(0.0), pytest.approx(1000.0)]

    def test_does_not_modify_input(self) -> None:
        butting = _member([600.0, 500.0], [0.0, 500.0])
        primary = _member([0.0, -1000.0], [0.0, 1000.0])
        resolve_member_interferences([primary, butting])
        assert butting['end'] == [0.0, 500.0]  # 元の命令は変更されない

    def test_order_independent(self) -> None:
        primary = _member([0.0, -1000.0], [0.0, 1000.0])
        butting = _member([600.0, 500.0], [0.0, 500.0], width=105.0)
        a = resolve_member_interferences([primary, butting])
        b = resolve_member_interferences([butting, primary])
        assert a[1]['end'] == pytest.approx(b[0]['end'])

    def test_trims_both_ends_between_two_primaries(self) -> None:
        left = _member([-300.0, -1000.0], [-300.0, 1000.0], member_id='L')
        right = _member([300.0, -1000.0], [300.0, 1000.0], member_id='R')
        mid = _member([-300.0, 0.0], [300.0, 0.0], width=105.0, member_id='mid')

        result = resolve_member_interferences([left, right, mid])
        m = next(c for c in result if c['member_id'] == 'mid')
        # 両端を各通し材の手前の面 (幅120 → 60) まで詰める
        assert m['start'] == [pytest.approx(-240.0), pytest.approx(0.0)]
        assert m['end'] == [pytest.approx(240.0), pytest.approx(0.0)]

    def test_parallel_beams_not_trimmed(self) -> None:
        a = _member([0.0, 0.0], [1000.0, 0.0])
        b = _member([1000.0, 0.0], [2000.0, 0.0])  # 同一直線上の継ぎ手
        result = resolve_member_interferences([a, b])
        assert result[0]['end'] == [pytest.approx(1000.0), pytest.approx(0.0)]
        assert result[1]['start'] == [pytest.approx(1000.0), pytest.approx(0.0)]

    def test_symmetric_l_corner_not_trimmed(self) -> None:
        # 同寸の材が出隅で相互に食い込む対称な角（勝ち負けが付かない）は触らない
        a = _member([0.0, 0.0], [0.0, 1000.0], width=120.0, member_id='a')
        b = _member([1000.0, 0.0], [0.0, 0.0], width=120.0, member_id='b')
        result = resolve_member_interferences([a, b])
        assert result[0]['start'] == [pytest.approx(0.0), pytest.approx(0.0)]
        assert result[0]['end'] == [pytest.approx(0.0), pytest.approx(1000.0)]
        assert result[1]['end'] == [pytest.approx(0.0), pytest.approx(0.0)]
        assert result[1]['start'] == [pytest.approx(1000.0), pytest.approx(0.0)]

    def test_asymmetric_l_corner_trims_loser(self) -> None:
        """出隅で食い込みが非対称な場合、深く食い込む負け材だけを面まで詰める。

        勝ち材 (幅120, 半幅60) は垂直に x=0 を通り、負け材 (幅105) が水平に
        x=0（勝ち材の中心線）まで食い込む。負け材の方が深く食い込むため、
        負け材の端部を勝ち材の面 (x=60) まで詰める。勝ち材は変更しない。
        """
        winner = _member([0.0, 0.0], [0.0, 2000.0], width=120.0, member_id='win')
        loser = _member([1000.0, 0.0], [0.0, 0.0], width=105.0, member_id='lose')
        result = resolve_member_interferences([winner, loser])
        win = next(c for c in result if c['member_id'] == 'win')
        lose = next(c for c in result if c['member_id'] == 'lose')
        assert lose['end'] == [pytest.approx(60.0), pytest.approx(0.0)]
        assert lose['start'] == [pytest.approx(1000.0), pytest.approx(0.0)]
        assert win['start'] == [pytest.approx(0.0), pytest.approx(0.0)]
        assert win['end'] == [pytest.approx(0.0), pytest.approx(2000.0)]

    def test_diagonal_brace_corner_not_trimmed(self) -> None:
        # 同寸・同長の斜材が一点で交わる対称な角（火打等）は触らない
        d = 1000.0
        a = _member([0.0, 0.0], [d, d], width=105.0, member_id='a')
        b = _member([0.0, 0.0], [d, -d], width=105.0, member_id='b')
        result = resolve_member_interferences([a, b])
        assert result[0]['start'] == [pytest.approx(0.0), pytest.approx(0.0)]
        assert result[1]['start'] == [pytest.approx(0.0), pytest.approx(0.0)]

    def test_sloped_member_not_trimmed(self) -> None:
        """傾斜梁（両端の天端 Z が異なる材）は詰める側にも相手側にもしない。"""
        primary = _member([0.0, -1000.0], [0.0, 1000.0], member_id='primary')
        # 通し材に食い込む登り梁: 高さが一定でないため詰めない
        sloped = _member([600.0, 500.0], [0.0, 500.0], width=105.0,
                         elevation=473.0, end_elevation=973.0, member_id='sloped')
        result = resolve_member_interferences([primary, sloped])
        s = next(c for c in result if c['member_id'] == 'sloped')
        assert s['end'] == [pytest.approx(0.0), pytest.approx(500.0)]
        assert s['end_elevation'] == pytest.approx(973.0)

    def test_member_butting_sloped_member_not_trimmed(self) -> None:
        """傾斜梁を相手とする食い込みも調整しない（水平面内の矩形モデル外）。"""
        sloped = _member([0.0, -1000.0], [0.0, 1000.0],
                         elevation=473.0, end_elevation=1473.0, member_id='sloped')
        butting = _member([600.0, 500.0], [0.0, 500.0], width=105.0, member_id='butting')
        result = resolve_member_interferences([sloped, butting])
        b = next(c for c in result if c['member_id'] == 'butting')
        assert b['end'] == [pytest.approx(0.0), pytest.approx(500.0)]

    def test_non_overlapping_z_not_trimmed(self) -> None:
        # 上下に離れた段差梁（Z 範囲が重ならない）は干渉とみなさない
        primary = _member([0.0, -1000.0], [0.0, 1000.0], elevation=473.0)
        butting = _member([600.0, 500.0], [0.0, 500.0], elevation=0.0)  # 背 180 で離れる
        result = resolve_member_interferences([primary, butting])
        assert result[1]['end'] == [pytest.approx(0.0), pytest.approx(500.0)]

    def test_different_layers_not_trimmed(self) -> None:
        primary = _member([0.0, -1000.0], [0.0, 1000.0], layer='1-横架材天端')
        butting = _member([600.0, 500.0], [0.0, 500.0], layer='2-横架材天端')
        result = resolve_member_interferences([primary, butting])
        assert result[1]['end'] == [pytest.approx(0.0), pytest.approx(500.0)]

    def test_non_interfering_beam_unchanged(self) -> None:
        # 相手の幅内に達していない（食い込んでいない）端部は不変
        primary = _member([0.0, -1000.0], [0.0, 1000.0])
        far = _member([600.0, 500.0], [200.0, 500.0])  # 端点 x=200, 甲の面 x=60 より外
        result = resolve_member_interferences([primary, far])
        assert result[1]['end'] == [pytest.approx(200.0), pytest.approx(500.0)]

    def test_output_json_serializable(self) -> None:
        primary = _member([0.0, -1000.0], [0.0, 1000.0])
        butting = _member([600.0, 500.0], [0.0, 500.0])
        result = resolve_member_interferences([primary, butting])
        assert json.loads(json.dumps(result)) == result
