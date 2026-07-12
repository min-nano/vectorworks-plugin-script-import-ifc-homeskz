"""解析フェーズ (ifc.footing) のテスト。

純粋なジオメトリ補助関数は手書きの ``_Solid`` タプルで、命令組み立ては実 IFC
フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell
import ifcopenshell.guid

from vectorworks_plugin_import_ifc_homeskz.ifc import footing, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _identity_placement() -> footing._Placement:
    return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class TestShoelaceArea:
    def test_unit_square(self) -> None:
        square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert footing._shoelace_area(square) == 1.0

    def test_is_orientation_independent(self) -> None:
        cw: list[tuple[float, float]] = [(0.0, 0.0), (0.0, 2.0), (3.0, 2.0), (3.0, 0.0)]
        assert footing._shoelace_area(cw) == 6.0


class TestVerticalSlab:
    """鉛直押し出し(底盤): プロファイルがそのまま平面外形。"""

    def _solid(self) -> footing._Solid:
        # XY 平面の矩形プロファイル(4m×3m)を Z+ に厚み 0.15 で押し出し、
        # 底面を Z=-0.1 に置く(配置原点 Z=-0.1)。
        pl: footing._Placement = (
            (10.0, 20.0, -0.1), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        pts = [(-2.0, -1.5), (2.0, -1.5), (2.0, 1.5), (-2.0, 1.5)]
        return (pl, (0.0, 0.0, 1.0), 0.15, pts, (4.0, 3.0))

    def test_top_and_thickness(self) -> None:
        top, thickness = footing._z_top_and_thickness(self._solid())
        assert math.isclose(top, 0.05)
        assert math.isclose(thickness, 0.15)

    def test_footprint_is_profile(self) -> None:
        fp = footing._footprint(self._solid())
        assert fp == [(8.0, 18.5), (12.0, 18.5), (12.0, 21.5), (8.0, 21.5)]


class TestHorizontalSlab:
    """水平押し出し(地中梁・布基礎底盤): 平面外形は掃引した矩形。"""

    def _solid(self) -> footing._Solid:
        # 押し出し方向 = 世界 X、断面は局所 XY(局所X=世界Y、局所Y=世界Z(下向き))。
        # 局所X=(0,1,0)、局所Y=(0,0,-1)、局所Z=(1,0,0)。
        pl: footing._Placement = (
            (5.0, 7.0, -0.24), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0))
        # 断面: 第1座標(局所X=世界Y)が幅 [-0.29,0]、第2座標(局所Y=世界Z下向き)
        pts = [(0.0, 0.0), (-0.29, 0.0), (-0.29, 0.14), (0.0, 0.14)]
        return (pl, (1.0, 0.0, 0.0), 1.88, pts, None)

    def test_top_and_thickness(self) -> None:
        top, thickness = footing._z_top_and_thickness(self._solid())
        # 局所Y=(0,0,-1)。プロファイル第2座標 v∈[0,0.14] → 世界Z=-0.24 - v。
        # Z 範囲 [-0.38, -0.24] → 天端 -0.24、厚み 0.14。
        assert math.isclose(top, -0.24)
        assert math.isclose(thickness, 0.14)

    def test_footprint_is_swept_rectangle(self) -> None:
        fp = footing._footprint(self._solid())
        # 世界 Y は局所X(世界Y方向)に第1座標分: 7 + [-0.29, 0]。
        # 世界 X は押し出し方向(世界X)に [0, 1.88]: 5 + [0, 1.88]。
        xs = sorted({round(x, 2) for x, _y in fp})
        ys = sorted({round(y, 2) for _x, y in fp})
        assert xs == [5.0, 6.88]
        assert ys == [6.71, 7.0]


class TestAxisPlacementHelpers:
    def test_compose_translation(self) -> None:
        element = ((1.0, 2.0, 3.0), (1.0, 0.0, 0.0),
                   (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        item = ((10.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        origin, lx, _ly, _lz = footing._compose(element, item)
        assert origin == (11.0, 2.0, 3.0)
        assert lx == (1.0, 0.0, 0.0)


def _open(name: str) -> ifcopenshell.file:
    # サニタイズ付きで開く(古い ifcopenshell でも基礎を取りこぼさないため)
    return open_ifc(os.path.join(FIXTURES_DIR, name))


class TestBuildFromFixture:
    """実 IFC からの命令組み立て(伏図次郎)。"""

    FILENAME = '伏図次郎【2階】.ifc'

    def test_slab_top_elevation_is_largest_area_height(self) -> None:
        ifc = _open(self.FILENAME)
        # 底盤の大半(基礎底盤 IfcSlab)の天端は 50.0
        assert footing.resolve_slab_top_elevation(ifc) == 50.0

    def test_foundation_story_command(self) -> None:
        ifc = _open(self.FILENAME)
        story = footing.build_foundation_story_command(ifc)
        assert story is not None
        assert story['name'] == '基礎'
        assert story['suffix'] == 'F'
        assert story['elevation'] == 0.0
        assert story['levels'] == [
            {'type': 'GL', 'offset': 0.0, 'layer': 'F-立上り'},
            {'type': '底盤天端', 'offset': 50.0, 'layer': 'F-底盤'},
        ]

    def test_wall_commands_shape(self) -> None:
        ifc = _open(self.FILENAME)
        walls = footing.build_wall_commands(ifc)
        assert walls
        for wall in walls:
            assert wall['layer'] == 'F-立上り'
            assert wall['class'] == '04構造-01基礎-03立ち上がり'
            assert len(wall['start']) == 2 and len(wall['end']) == 2
            assert wall['thickness'] > 0
            assert wall['bottom_bound']['level'] == 'GL'
            assert wall['bottom_bound']['story_offset'] == 0
            assert wall['top_bound']['level'] == '横架材天端'
            assert wall['top_bound']['story_offset'] == 1

    def test_slab_commands_shape(self) -> None:
        ifc = _open(self.FILENAME)
        slabs = footing.build_slab_commands(ifc)
        assert slabs
        for slab in slabs:
            assert slab['layer'] == 'F-底盤'
            assert slab['class'] == '04構造-01基礎-02基礎スラブ'
            assert len(slab['boundary']) >= 3
            assert slab['thickness'] > 0
            assert slab['bound']['level'] == '底盤天端'
            assert slab['bound']['story_offset'] == 0
        # 主たる底盤は天端=底盤天端 (offset≈0)、地中梁は底盤天端より低い (offset<0)
        offsets = [round(s['bound']['offset'], 1) for s in slabs]
        assert 0.0 in offsets
        assert any(o < 0.0 for o in offsets)


class TestNoFoundation:
    def test_returns_none_and_empty_when_absent(self) -> None:
        # 空の IFC には基礎要素が無い
        ifc = ifcopenshell.file(schema='IFC2X3')
        assert footing.has_foundation(ifc) is False
        assert footing.build_foundation_story_command(ifc) is None
        assert footing.resolve_slab_top_elevation(ifc) is None
        assert footing.build_wall_commands(ifc) == []
        assert footing.build_slab_commands(ifc) == []


# --- 合成エンティティを使った防御的分岐(不正/欠損ジオメトリ)のテスト ---

def _f() -> ifcopenshell.file:
    return ifcopenshell.file(schema='IFC4')


def _pt(f: ifcopenshell.file, *c: float) -> ifcopenshell.entity_instance:
    return f.create_entity('IfcCartesianPoint', Coordinates=[float(x) for x in c])


def _d(f: ifcopenshell.file, *c: float) -> ifcopenshell.entity_instance:
    return f.create_entity('IfcDirection', DirectionRatios=[float(x) for x in c])


def _ax3(
    f: ifcopenshell.file,
    axis: tuple[float, float, float] | None = None,
    ref: tuple[float, float, float] | None = None,
) -> ifcopenshell.entity_instance:
    return f.create_entity(
        'IfcAxis2Placement3D', Location=_pt(f, 0.0, 0.0, 0.0),
        Axis=_d(f, *axis) if axis else None,
        RefDirection=_d(f, *ref) if ref else None)


def _extruded(
    f: ifcopenshell.file, profile: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    return f.create_entity(
        'IfcExtrudedAreaSolid', SweptArea=profile, Position=_ax3(f),
        ExtrudedDirection=_d(f, 0.0, 0.0, 1.0), Depth=1880.0)


def _rect(f: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return f.create_entity('IfcRectangleProfileDef', ProfileType='AREA',
                           XDim=120.0, YDim=500.0)


def _arb(f: ifcopenshell.file) -> ifcopenshell.entity_instance:
    poly = f.create_entity('IfcPolyline', Points=[
        _pt(f, 0.0, 0.0), _pt(f, 100.0, 0.0),
        _pt(f, 100.0, 50.0), _pt(f, 0.0, 50.0)])
    return f.create_entity('IfcArbitraryClosedProfileDef', ProfileType='AREA',
                           OuterCurve=poly)


def _circle_profile(f: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return f.create_entity('IfcCircleProfileDef', ProfileType='AREA', Radius=100.0)


def _shape(
    f: ifcopenshell.file, *items: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    rep = f.create_entity('IfcShapeRepresentation', Items=list(items))
    return f.create_entity('IfcProductDefinitionShape', Representations=[rep])


def _footing(
    f: ifcopenshell.file, name: str,
    rep: ifcopenshell.entity_instance | None = None, placement: bool = True,
) -> ifcopenshell.entity_instance:
    return f.create_entity(
        'IfcFooting', GlobalId=ifcopenshell.guid.new(), Name=name,
        ObjectPlacement=(f.create_entity('IfcLocalPlacement',
                                         RelativePlacement=_ax3(f))
                         if placement else None),
        Representation=rep)


class TestGeometryHelperGuards:
    def test_axis_placement_degenerate_refdirection(self) -> None:
        # RefDirection が Axis と平行 → 直交化で 0 ベクトルになり既定 X 軸へ戻す
        f = _f()
        _origin, lx, _ly, _lz = footing._axis_placement(
            _ax3(f, axis=(0.0, 0.0, 1.0), ref=(0.0, 0.0, 1.0)))
        assert lx == (1.0, 0.0, 0.0)

    def test_base_extruded_solid_returns_none_for_non_solid(self) -> None:
        f = _f()
        assert footing._base_extruded_solid(_pt(f, 0.0, 0.0, 0.0)) is None

    def test_first_extruded_solid_none_without_representation(self) -> None:
        f = _f()
        assert footing._first_extruded_solid(_footing(f, 'x', rep=None)) is None

    def test_first_extruded_solid_none_without_solid_items(self) -> None:
        f = _f()
        rep = _shape(f, _pt(f, 0.0, 0.0, 0.0))
        assert footing._first_extruded_solid(_footing(f, 'x', rep=rep)) is None

    def test_profile_points_none_for_unsupported_profile(self) -> None:
        f = _f()
        assert footing._profile_points(_circle_profile(f)) is None

    def test_profile_points_none_for_non_polyline_outer_curve(self) -> None:
        f = _f()
        circle = f.create_entity(
            'IfcCircle',
            Position=f.create_entity('IfcAxis2Placement2D',
                                     Location=_pt(f, 0.0, 0.0)),
            Radius=100.0)
        arb = f.create_entity('IfcArbitraryClosedProfileDef', ProfileType='AREA',
                              OuterCurve=circle)
        assert footing._profile_points(arb) is None

    def test_world_solid_none_without_solid(self) -> None:
        f = _f()
        assert footing._world_solid(_footing(f, 'x', rep=None)) is None

    def test_world_solid_none_without_placement(self) -> None:
        f = _f()
        rep = _shape(f, _extruded(f, _rect(f)))
        assert footing._world_solid(
            _footing(f, 'x', rep=rep, placement=False)) is None

    def test_world_solid_none_for_unsupported_profile(self) -> None:
        f = _f()
        rep = _shape(f, _extruded(f, _circle_profile(f)))
        assert footing._world_solid(_footing(f, 'x', rep=rep)) is None


class TestBuildSkipsMalformedElements:
    """ジオメトリが欠損/非対応の基礎要素は命令を生成せずスキップする。"""

    def _file_with_malformed_footings(self) -> ifcopenshell.file:
        f = _f()
        f.create_entity('IfcBuildingStorey', GlobalId=ifcopenshell.guid.new(),
                        Name='1FL', Elevation=600.0)
        # 立上り: ジオメトリ無し(solid None) と 非矩形断面(dims None)
        _footing(f, '基礎梁:nogeom', rep=None)
        _footing(f, '基礎梁:arb', rep=_shape(f, _extruded(f, _arb(f))))
        # 地中梁・底盤: ジオメトリ無し(solid None)
        _footing(f, '地中梁:nogeom', rep=None)
        _footing(f, '基礎底盤:nogeom', rep=None)
        return f

    def test_walls_skip_missing_and_non_rectangular(self) -> None:
        f = self._file_with_malformed_footings()
        assert footing.build_wall_commands(f) == []

    def test_slabs_skip_missing_geometry(self) -> None:
        f = self._file_with_malformed_footings()
        assert footing.build_slab_commands(f) == []

    def test_slab_top_elevation_none_when_base_slab_has_no_geometry(self) -> None:
        f = self._file_with_malformed_footings()
        assert footing.resolve_slab_top_elevation(f) is None
