"""解析フェーズ (ifc.footing) のテスト。

純粋なジオメトリ補助関数は手書きの ``_Solid`` タプルで、命令組み立ては実 IFC
フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

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
