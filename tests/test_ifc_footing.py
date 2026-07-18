"""解析フェーズ (ifc.footing) のテスト。

純粋なジオメトリ補助関数は手書きの ``_Solid`` タプルで、命令組み立ては実 IFC
フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math

import ifcopenshell
import ifcopenshell.guid

from vectorworks_plugin_import_ifc_homeskz.ifc import footing

from tests.conftest import load_fixture_ifc


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
    return load_fixture_ifc(name)


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
        # 並びは希望スタック順(上→下): 基礎天端(アンカーボルト) → GL(立上り)
        # → 床束 → 底盤天端(底盤)。基礎天端は立上り天端 400.0、床束は底盤上端 50.0。
        assert story['levels'] == [
            {'type': '基礎天端', 'offset': 400.0, 'layer': 'F-アンカーボルト'},
            {'type': 'GL', 'offset': 0.0, 'layer': 'F-立上り'},
            {'type': '床束', 'offset': 50.0, 'layer': 'F-床束'},
            {'type': '底盤天端', 'offset': 50.0, 'layer': 'F-底盤'},
        ]

    def test_foundation_top_elevation_is_wall_top(self) -> None:
        ifc = _open(self.FILENAME)
        # 基礎天端 = 立上り(基礎梁)天端の最大値
        assert footing.resolve_foundation_top_elevation(ifc) == 400.0

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

    def test_walls_are_merged(self) -> None:
        # 同一直線・同一断面の立上りが統合され、残った壁同士に統合可能ペアが無い
        ifc = _open(self.FILENAME)
        walls = footing.build_wall_commands(ifc)
        for i in range(len(walls)):
            for j in range(i + 1, len(walls)):
                if (footing._wall_section_key(walls[i])
                        == footing._wall_section_key(walls[j])):
                    assert not footing._walls_connected_collinear(
                        walls[i], walls[j])

    def test_slab_commands_shape(self) -> None:
        ifc = _open(self.FILENAME)
        slabs = footing.build_slab_commands(ifc)
        assert slabs
        slab_top = footing.resolve_slab_top_elevation(ifc)
        assert slab_top is not None
        for slab in slabs:
            assert slab['layer'] == 'F-底盤'
            assert slab['class'] == '04構造-01基礎-02基礎スラブ'
            assert len(slab['boundary']) >= 3
            assert slab['bound']['level'] == '底盤天端'
            assert slab['bound']['story_offset'] == 0
            # elevation は天端の絶対 Z、bound.offset は底盤天端(絶対)との差
            assert math.isclose(
                slab['elevation'], slab_top + slab['bound']['offset'])
            # スラブは底盤のみ(地中梁はモディファイア)。厚みは正の整数 mm。
            thickness = slab['thickness']
            assert thickness is not None
            assert thickness > 0.0 and thickness == round(thickness)
            assert isinstance(slab['modifiers'], list)
        # 主たる底盤は天端=底盤天端 (offset≈0)、独立基礎底盤は別高さ (offset≠0)
        offsets = [round(s['bound']['offset'], 1) for s in slabs]
        assert 0.0 in offsets
        # 地中梁は単独スラブではなく、底盤スラブのモディファイアとして持つ。
        # 台形プリズムの総数はフィクスチャの地中梁数(伏図次郎=23)と一致する。
        total_modifiers = sum(len(s['modifiers']) for s in slabs)
        assert total_modifiers == 23
        # モディファイアを持つ底盤が少なくとも 1 枚ある。
        assert any(s['modifiers'] for s in slabs)

    def test_continuous_base_slabs_are_merged(self) -> None:
        # 連続する同厚の基礎底盤(ベタ基礎)は 1 枚に統合される。伏図次郎は
        # offset=0 の底盤 12 枚が 1 枚の L 字ポリゴンに、独立基礎底盤(offset≠0)は
        # そのまま残る。統合後は同一グループに連続する矩形ペアが残らない。
        ifc = _open(self.FILENAME)
        slabs = footing.build_slab_commands(ifc)
        base = [s for s in slabs if s['thickness'] is not None]
        # 12 枚の連続底盤 → 1 枚。独立基礎底盤は別高さ(別グループ)で残る。
        assert len(base) == 2
        merged = max(base, key=lambda s: len(s['boundary']))
        assert len(merged['boundary']) > 4  # L 字(6 頂点)

    def test_base_slab_outer_boundary_matches_wall_outer_face(self) -> None:
        # 底盤外形は立上りの壁心にあるため、外面(壁心 + 半壁厚)まで広がる。
        # 伏図次郎の外周立上りは全て 120mm 厚。統合底盤の外周(最大 x)が、統合前
        # (壁心)の外周より半壁厚(60mm)外へ動いていることを確認する。
        ifc = _open(self.FILENAME)
        walls = footing.build_wall_commands(ifc)
        with_face = footing.build_slab_commands(ifc, walls)
        # 外面合わせを掛けない場合(壁心のまま)の統合底盤
        centerline = footing.build_slab_commands(ifc, [])
        big_face = max((s for s in with_face if s['thickness'] is not None),
                       key=lambda s: len(s['boundary']))
        big_center = max((s for s in centerline if s['thickness'] is not None),
                         key=lambda s: len(s['boundary']))
        face_max_x = max(x for x, _y in big_face['boundary'])
        center_max_x = max(x for x, _y in big_center['boundary'])
        # 壁厚 120 の半分だけ外へ動いている
        assert math.isclose(face_max_x - center_max_x, 60.0, abs_tol=0.5)


class TestGroundBeamModifier:
    """地中梁 → 台形プリズムのモディファイア変換 (``_ground_beam_modifier``)。"""

    def test_geometry_from_horizontal_solid(self) -> None:
        # 水平押し出し(+X)・鉛直断面(ly=+Z)の台形地中梁。
        placement: footing._Placement = (
            (1000.0, 2000.0, -240.0),
            (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
        pts = [(0.0, 0.0), (-150.0, 0.0), (-290.0, 140.0), (0.0, 140.0)]
        solid: footing._Solid = (
            placement, (1.0, 0.0, 0.0), 1060.0, pts, None)
        mod = footing._ground_beam_modifier(solid, 100.0, 200.0)
        assert mod is not None
        assert math.isclose(mod['depth'], 1060.0)
        assert math.isclose(mod['azimuth'], 0.0)
        # XY はセンタリング済み、z は絶対値(梁下端)。
        assert mod['origin'] == [900.0, 1800.0, -240.0]
        # 幅軸 u・鉛直軸 v の断面。この配置では元の (u, v) と一致する。
        for got, want in zip(mod['profile'], pts):
            assert math.isclose(got[0], want[0])
            assert math.isclose(got[1], want[1])

    def test_vertical_extrude_returns_none(self) -> None:
        # 鉛直押し出しは地中梁でない(通常起きない)ため None。
        solid: footing._Solid = (
            _identity_placement(), (0.0, 0.0, 1.0), 100.0,
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], None)
        assert footing._ground_beam_modifier(solid, 0.0, 0.0) is None

    def test_azimuth_from_run_direction(self) -> None:
        # 押し出し +Y → 方位角 90 度。
        placement: footing._Placement = (
            (0.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
        solid: footing._Solid = (
            placement, (0.0, 1.0, 0.0), 500.0,
            [(0.0, 0.0), (-150.0, 0.0), (-290.0, 140.0), (0.0, 140.0)], None)
        mod = footing._ground_beam_modifier(solid, 0.0, 0.0)
        assert mod is not None
        assert math.isclose(mod['azimuth'], 90.0)

    def test_modifiers_roundtrip_to_solid_world(self) -> None:
        # モディファイアの (profile, origin, azimuth, depth) が、描画フェーズの回転
        # 規約(Rotate3D(90,0,0) → Rotate3D(0,0,azimuth+90) → Move3D(origin))で
        # 元ソリッドのワールド座標(センタリング済み)を復元する。
        from vectorworks_plugin_import_ifc_homeskz.ifc.grid import resolve_lines
        ifc = _open('伏図次郎【2階】.ifc')
        _lines, cx, cy = resolve_lines(ifc)
        beams = [e for e in ifc.by_type('IfcFooting')
                 if '地中梁' in (e.Name or '')]
        assert beams
        max_err = 0.0
        checked = 0
        for element in beams:
            solid = footing._world_solid(element)
            if solid is None:
                continue
            (o, lx, ly, _lz), ex, depth, pts, _dims = solid
            mod = footing._ground_beam_modifier(solid, cx, cy)
            assert mod is not None
            phi = math.radians(mod['azimuth'] + 90.0)
            for (u, v), (pu, pv) in zip(pts, mod['profile']):
                for t in (0.0, depth):
                    base = (o[0] + lx[0] * u + ly[0] * v,
                            o[1] + lx[1] * u + ly[1] * v,
                            o[2] + lx[2] * u + ly[2] * v)
                    true = (base[0] + ex[0] * t - cx,
                            base[1] + ex[1] * t - cy,
                            base[2] + ex[2] * t)
                    got = (mod['origin'][0] + pu * math.cos(phi)
                           + t * math.sin(phi),
                           mod['origin'][1] + pu * math.sin(phi)
                           - t * math.cos(phi),
                           mod['origin'][2] + pv)
                    max_err = max(max_err,
                                  max(abs(true[i] - got[i]) for i in range(3)))
                    checked += 1
        assert checked > 0
        assert max_err < 1e-6


class TestAttachGroundBeamModifiers:
    """地中梁モディファイアの底盤への振り分け (``_attach_ground_beam_modifiers``)。"""

    def test_attached_to_overlapping_slab(self) -> None:
        slabs = [_slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
                 _slab(_rect_boundary(5000.0, 0.0, 6000.0, 1000.0))]
        mod = _modifier([400.0, 400.0, -240.0])
        footprint = [(300.0, 300.0), (700.0, 300.0),
                     (700.0, 700.0), (300.0, 700.0)]
        footing._attach_ground_beam_modifiers(slabs, [(mod, footprint)])
        assert slabs[0]['modifiers'] == [mod]
        assert slabs[1]['modifiers'] == []

    def test_nonoverlapping_falls_back_to_nearest(self) -> None:
        slabs = [_slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
                 _slab(_rect_boundary(5000.0, 0.0, 6000.0, 1000.0))]
        mod = _modifier([5500.0, 3000.0, -240.0])
        # どちらの底盤の外にもあるが、重心は 2 枚目の底盤に近い。
        footprint = [(5400.0, 3000.0), (5600.0, 3000.0),
                     (5600.0, 3100.0), (5400.0, 3100.0)]
        footing._attach_ground_beam_modifiers(slabs, [(mod, footprint)])
        assert slabs[0]['modifiers'] == []
        assert slabs[1]['modifiers'] == [mod]

    def test_no_slabs_drops_silently(self) -> None:
        slabs: list[footing.SlabCommand] = []
        mod = _modifier([0.0, 0.0, 0.0])
        footprint = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        # 底盤が無ければ付けられず捨てる(例外は出ない)。
        footing._attach_ground_beam_modifiers(slabs, [(mod, footprint)])
        assert slabs == []

    def test_build_slab_commands_attaches_all_ground_beams(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        slabs = footing.build_slab_commands(ifc)
        beams = [e for e in ifc.by_type('IfcFooting')
                 if '地中梁' in (e.Name or '')]
        # 全地中梁がいずれかの底盤のモディファイアに収まる(取りこぼさない)。
        assert sum(len(s['modifiers']) for s in slabs) == len(beams)
        # スラブは底盤のみ(地中梁の単独スラブは無い)。
        assert all(s['thickness'] is not None for s in slabs)


def _slab(
    boundary: list[list[float]], thickness: float | None = 150.0,
    offset: float = 0.0, layer: str = footing.LAYER_FOUNDATION_SLAB,
) -> footing.SlabCommand:
    return {
        'layer': layer,
        'class': footing.CLASS_FOUNDATION_SLAB,
        'boundary': boundary,
        'elevation': 50.0 + offset,
        'thickness': thickness,
        'bound': {
            'story_offset': 0, 'level': footing.LEVEL_SLAB_TOP, 'offset': offset},
        'modifiers': [],
    }


def _modifier(
    origin: list[float], azimuth: float = 0.0,
) -> footing.ModifierCommand:
    return {
        'profile': [[0.0, 0.0], [-150.0, 0.0], [-290.0, 140.0], [0.0, 140.0]],
        'depth': 1000.0,
        'origin': origin,
        'azimuth': azimuth,
    }


def _rect_boundary(
    x1: float, y1: float, x2: float, y2: float,
) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class TestMergeSlabCommands:
    """連続する同厚・同高さの底盤(基礎底盤系)を 1 枚に統合する。"""

    def test_two_adjacent_rects_merge_into_one(self) -> None:
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
            _slab(_rect_boundary(1000.0, 0.0, 2000.0, 1000.0)),
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 1
        xs = [x for x, _y in merged[0]['boundary']]
        ys = [y for _x, y in merged[0]['boundary']]
        assert min(xs) == 0.0 and max(xs) == 2000.0
        assert min(ys) == 0.0 and max(ys) == 1000.0
        assert len(merged[0]['boundary']) == 4  # 1 つの矩形

    def test_l_shape_merge_has_six_vertices(self) -> None:
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 2000.0, 2000.0)),
            _slab(_rect_boundary(0.0, 2000.0, 1000.0, 3000.0)),
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 1
        assert len(merged[0]['boundary']) == 6

    def test_gap_between_rects_not_merged(self) -> None:
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
            _slab(_rect_boundary(1100.0, 0.0, 2000.0, 1000.0)),
        ]
        assert len(footing.merge_slab_commands(slabs)) == 2

    def test_corner_touching_not_merged(self) -> None:
        # 角(点)だけで接する底盤は連続とみなさない
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
            _slab(_rect_boundary(1000.0, 1000.0, 2000.0, 2000.0)),
        ]
        assert len(footing.merge_slab_commands(slabs)) == 2

    def test_different_thickness_not_merged(self) -> None:
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0), thickness=150.0),
            _slab(_rect_boundary(1000.0, 0.0, 2000.0, 1000.0), thickness=180.0),
        ]
        assert len(footing.merge_slab_commands(slabs)) == 2

    def test_different_height_not_merged(self) -> None:
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0), offset=0.0),
            _slab(_rect_boundary(1000.0, 0.0, 2000.0, 1000.0), offset=-100.0),
        ]
        assert len(footing.merge_slab_commands(slabs)) == 2

    def test_ground_beams_not_merged(self) -> None:
        # 地中梁(thickness=None)は連続していても統合しない
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0), thickness=None),
            _slab(_rect_boundary(1000.0, 0.0, 2000.0, 1000.0), thickness=None),
        ]
        assert len(footing.merge_slab_commands(slabs)) == 2

    def test_ring_with_hole_not_merged(self) -> None:
        # 中空(穴)になる連結成分は単一境界で表せないため統合しない(元のまま)。
        # 4 本の帯で四角い輪(中央に穴)を作る。
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 3000.0, 500.0)),      # 下辺
            _slab(_rect_boundary(0.0, 2500.0, 3000.0, 3000.0)),  # 上辺
            _slab(_rect_boundary(0.0, 0.0, 500.0, 3000.0)),      # 左辺
            _slab(_rect_boundary(2500.0, 0.0, 3000.0, 3000.0)),  # 右辺
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 4  # 穴があるため統合されず元のまま

    def test_single_slab_passthrough_unchanged(self) -> None:
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0))
        merged = footing.merge_slab_commands([slab])
        assert merged == [slab]

    def test_chamfered_slab_merges_with_diagonal_edge(self) -> None:
        # 斜め辺(45 度取合い)を持つ底盤も、連続する矩形底盤と 1 枚に統合される
        # (任意向きの多角形和のため、軸平行以外の辺も扱える)。
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 2000.0, 2000.0)),
            _slab(_rect_boundary(2000.0, 0.0, 4000.0, 2000.0)),
            # 上に載る五角形(右上が 45 度に欠けた形)
            _slab([[0.0, 2000.0], [2000.0, 2000.0], [2000.0, 3000.0],
                   [1000.0, 3000.0]]),
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 1
        pts = merged[0]['boundary']
        # 斜め辺(x も y も動く辺)が外形に含まれる
        assert any(a[0] != b[0] and a[1] != b[1]
                   for a, b in zip(pts, pts[1:] + pts[:1]))

    def test_rotated_group_merges(self) -> None:
        # グリッドごと回転した底盤群(斜めの建物)も連続していれば統合される。
        def rot(boundary: list[list[float]], deg: float) -> list[list[float]]:
            a = math.radians(deg)
            c, s = math.cos(a), math.sin(a)
            return [[x * c - y * s, x * s + y * c] for x, y in boundary]

        slabs = [
            _slab(rot(_rect_boundary(0.0, 0.0, 2000.0, 1000.0), 30.0)),
            _slab(rot(_rect_boundary(2000.0, 0.0, 4000.0, 1000.0), 30.0)),
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 1

    def test_disjoint_groups_stay_separate(self) -> None:
        # 連続する 2 枚 + 離れた 1 枚 → 統合 1 枚 + 単独 1 枚 = 2 枚
        slabs = [
            _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0)),
            _slab(_rect_boundary(1000.0, 0.0, 2000.0, 1000.0)),
            _slab(_rect_boundary(5000.0, 5000.0, 6000.0, 6000.0)),
        ]
        merged = footing.merge_slab_commands(slabs)
        assert len(merged) == 2

    def test_empty_returns_empty(self) -> None:
        assert footing.merge_slab_commands([]) == []


class TestAlignSlabsToWallFaces:
    """底盤の外周を立上りの外面(壁心 + 半壁厚)まで外側へ広げる。"""

    def test_edge_on_wall_centerline_offsets_outward(self) -> None:
        # 200mm 厚の立上りが底盤の 4 辺の壁心に沿う → 各辺が半壁厚 100 外へ広がる
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0))
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0], thickness=200.0),
            _wall([1000.0, 0.0], [1000.0, 1000.0], thickness=200.0),
            _wall([1000.0, 1000.0], [0.0, 1000.0], thickness=200.0),
            _wall([0.0, 1000.0], [0.0, 0.0], thickness=200.0),
        ]
        result = footing.align_slabs_to_wall_faces([slab], walls)
        assert len(result) == 1
        xs = [x for x, _y in result[0]['boundary']]
        ys = [y for _x, y in result[0]['boundary']]
        assert min(xs) == -100.0 and max(xs) == 1100.0
        assert min(ys) == -100.0 and max(ys) == 1100.0

    def test_edge_without_wall_not_moved(self) -> None:
        # 沿う立上りが無い底盤(独立基礎底盤等)は動かさない
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0))
        far_wall = _wall([9000.0, 9000.0], [9000.0, 10000.0], thickness=200.0)
        result = footing.align_slabs_to_wall_faces([slab], [far_wall])
        assert result[0]['boundary'] == slab['boundary']

    def test_ground_beam_not_offset(self) -> None:
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0), thickness=None)
        walls = [_wall([0.0, 0.0], [1000.0, 0.0], thickness=200.0)]
        result = footing.align_slabs_to_wall_faces([slab], walls)
        assert result[0]['boundary'] == slab['boundary']

    def test_no_walls_returns_unchanged(self) -> None:
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0))
        assert footing.align_slabs_to_wall_faces([slab], []) == [slab]

    def test_per_edge_thickness(self) -> None:
        # 上辺だけ 300mm 厚の立上り、他辺は立上り無し → 上辺だけ 150 外へ広がる
        slab = _slab(_rect_boundary(0.0, 0.0, 1000.0, 1000.0))
        walls = [_wall([0.0, 1000.0], [1000.0, 1000.0], thickness=300.0)]
        result = footing.align_slabs_to_wall_faces([slab], walls)
        ys = [y for _x, y in result[0]['boundary']]
        assert max(ys) == 1150.0   # 上辺は外面(1000 + 150)へ
        assert min(ys) == 0.0      # 下辺は動かない


def _wall(
    start: list[float], end: list[float], thickness: float = 120.0,
    bottom_offset: float = -100.0, top_offset: float = -190.0,
) -> footing.WallCommand:
    return {
        'layer': footing.LAYER_FOUNDATION_WALL,
        'class': footing.CLASS_FOUNDATION_WALL,
        'start': start,
        'end': end,
        'thickness': thickness,
        'bottom_bound': {
            'story_offset': 0, 'level': footing.LEVEL_GL, 'offset': bottom_offset},
        'top_bound': {
            'story_offset': 1, 'level': footing.LEVEL_BEAM_TOP, 'offset': top_offset},
    }


def _col(x: float, y: float) -> footing.ColumnCommand:
    """自由端の終端柱判定用の最小の柱命令(位置のみ使う)。"""
    return {
        'layer': '1to2-柱',
        'member_id': '105×105 - 管柱',
        'class': '04構造-02木造-08柱-01管柱',
        'structural_use': '4',
        'position': [x, y],
        'width': 105.0,
        'depth': 105.0,
        'height': 2800.0,
        'elevation': 0.0,
        'top_hardware': '',
        'bottom_hardware': '',
        'bottom_bound': {
            'story_offset': 0, 'level': footing.LEVEL_BEAM_TOP, 'offset': 0.0},
        'top_bound': {
            'story_offset': 1, 'level': footing.LEVEL_BEAM_TOP, 'offset': 0.0},
    }


class TestMergeWallCommands:
    """同一直線上・同一断面の立上りを 1 本に統合する。"""

    def test_collinear_touching_merge_into_one(self) -> None:
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0]),
            _wall([1000.0, 0.0], [3000.0, 0.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 1
        assert merged[0]['start'] == [0.0, 0.0]
        assert merged[0]['end'] == [3000.0, 0.0]
        assert merged[0]['thickness'] == 120.0
        assert merged[0]['bottom_bound']['offset'] == -100.0
        assert merged[0]['top_bound']['offset'] == -190.0

    def test_overlapping_segments_merge(self) -> None:
        walls = [
            _wall([0.0, 0.0], [2000.0, 0.0]),
            _wall([1500.0, 0.0], [3000.0, 0.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 1
        assert merged[0]['start'] == [0.0, 0.0]
        assert merged[0]['end'] == [3000.0, 0.0]

    def test_chain_of_three_merges(self) -> None:
        walls = [
            _wall([0.0, 5.0], [0.0, 1000.0]),
            _wall([0.0, 1000.0], [0.0, 2000.0]),
            _wall([0.0, 2000.0], [0.0, 3000.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 1
        ys = sorted([merged[0]['start'][1], merged[0]['end'][1]])
        assert ys == [5.0, 3000.0]
        assert merged[0]['start'][0] == 0.0 and merged[0]['end'][0] == 0.0

    def test_gap_between_collinear_segments_not_merged(self) -> None:
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0]),
            _wall([2000.0, 0.0], [3000.0, 0.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 2

    def test_parallel_offset_lines_not_merged(self) -> None:
        # 平行だが別の線上(直交距離 = 壁厚分)は統合しない
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([0.0, 120.0], [3000.0, 120.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 2

    def test_perpendicular_touching_not_merged(self) -> None:
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([3000.0, 0.0], [3000.0, 3000.0]),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 2

    def test_different_thickness_not_merged(self) -> None:
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0], thickness=120.0),
            _wall([1000.0, 0.0], [3000.0, 0.0], thickness=150.0),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 2

    def test_different_height_not_merged(self) -> None:
        # 同一直線・接触でも高さ(top_bound offset)が違えば別断面として残す
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0], top_offset=-190.0),
            _wall([1000.0, 0.0], [3000.0, 0.0], top_offset=-540.0),
        ]
        merged = footing.merge_wall_commands(walls)
        assert len(merged) == 2

    def test_empty_returns_empty(self) -> None:
        assert footing.merge_wall_commands([]) == []


class TestExtendFreeWallEnds:
    """他の立上りと交差しない端点を半壁厚だけ外側へ延長する。"""

    def test_isolated_wall_extends_both_ends(self) -> None:
        # どの立上りとも交差しない立上り → 両端を半壁厚(60)ずつ外側へ延長
        walls = [_wall([0.0, 0.0], [3000.0, 0.0], thickness=120.0)]
        ext = footing._extend_free_wall_ends(walls)
        assert ext[0]['start'] == [-60.0, 0.0]
        assert ext[0]['end'] == [3060.0, 0.0]

    def test_extension_follows_wall_axis(self) -> None:
        # 延長方向は壁芯(自分の軸)に沿う。始点は始点側・終点は終点側へ。
        walls = [_wall([0.0, 0.0], [0.0, 2000.0], thickness=150.0)]
        ext = footing._extend_free_wall_ends(walls)
        assert ext[0]['start'] == [0.0, -75.0]
        assert ext[0]['end'] == [0.0, 2075.0]

    def test_l_corner_joined_ends_not_extended(self) -> None:
        # コーナーで交わる端点は延長せず、反対側(自由端)だけ延長する
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([0.0, 0.0], [0.0, 3000.0]),
        ]
        ext = footing._extend_free_wall_ends(walls)
        assert ext[0]['start'] == [0.0, 0.0]      # コーナー(交差)側は据え置き
        assert ext[0]['end'] == [3060.0, 0.0]     # 自由端は延長
        assert ext[1]['start'] == [0.0, 0.0]
        assert ext[1]['end'] == [0.0, 3060.0]

    def test_t_through_wall_ends_extended_stem_butt_not(self) -> None:
        # 通し材に突き当たる stem の端点は据え置き、通し材の両自由端は延長
        through = _wall([0.0, 0.0], [3000.0, 0.0])
        stem = _wall([1500.0, 0.0], [1500.0, 2000.0])
        ext = footing._extend_free_wall_ends([through, stem])
        assert ext[0]['start'] == [-60.0, 0.0]    # 通し材の自由端
        assert ext[0]['end'] == [3060.0, 0.0]
        assert ext[1]['start'] == [1500.0, 0.0]   # 突き当て側(交差)は据え置き
        assert ext[1]['end'] == [1500.0, 2060.0]  # 反対の自由端は延長

    def test_zero_length_wall_unchanged(self) -> None:
        walls = [_wall([100.0, 100.0], [100.0, 100.0])]
        ext = footing._extend_free_wall_ends(walls)
        assert ext[0]['start'] == [100.0, 100.0]
        assert ext[0]['end'] == [100.0, 100.0]

    def test_walls_on_different_layers_do_not_interact(self) -> None:
        # レイヤが違う立上りは交差判定の対象外。同レイヤなら交差する端点でも
        # 別レイヤなら自由端扱いになり、両方とも全端が延長される。
        a = _wall([0.0, 0.0], [3000.0, 0.0])
        b = _wall([0.0, 0.0], [0.0, 3000.0])
        b['layer'] = 'F-別レイヤ'
        ext = footing._extend_free_wall_ends([a, b])
        assert ext[0]['start'] == [-60.0, 0.0]
        assert ext[0]['end'] == [3060.0, 0.0]
        assert ext[1]['start'] == [0.0, -60.0]
        assert ext[1]['end'] == [0.0, 3060.0]

    def test_empty_returns_empty(self) -> None:
        assert footing._extend_free_wall_ends([]) == []

    def test_free_end_snaps_to_terminal_column_center(self) -> None:
        # 半島状の自由端が柱芯より外側(土台の半材せいぶん=52mm)に入力されて
        # いても、終端柱の柱芯 + 半壁厚に揃える。150mm 壁・柱芯 y=5460・自由端
        # y=5512 → 柱芯へ寄せてから半壁厚(75)延長 → y=5535(柱芯 + 75)。
        wall = _wall([0.0, 5512.0], [0.0, 4550.0], thickness=150.0)
        columns = [_col(0.0, 5460.0)]
        ext = footing._extend_free_wall_ends([wall], columns)
        assert ext[0]['start'] == [0.0, 5535.0]   # 柱芯 5460 + 半壁厚 75
        # end も自由端だが柱が無いため端点から半壁厚(75)延長される(5512→4475)
        assert ext[0]['end'] == [0.0, 4475.0]

    def test_free_end_at_column_center_extends_half_thickness(self) -> None:
        # 柱芯 = 自由端(overshoot 0)なら従来どおり半壁厚だけ延長する(柱芯へ
        # 寄せても位置は変わらない)。120mm 壁・柱芯=自由端 y=3000 → y=3060。
        wall = _wall([0.0, 0.0], [0.0, 3000.0], thickness=120.0)
        columns = [_col(0.0, 3000.0)]
        ext = footing._extend_free_wall_ends([wall], columns)
        assert ext[0]['end'] == [0.0, 3060.0]      # 柱芯 3000 + 半壁厚 60
        assert ext[0]['start'] == [0.0, -60.0]     # 柱の無い始端は端点から半壁厚

    def test_far_column_is_not_used_as_terminal(self) -> None:
        # 沿軸許容(150mm)を超えて内側にある柱は終端柱にしない(隣モジュールの
        # 柱を拾わない)。自由端 y=5512・柱 y=5000(512mm 内側) → 柱芯へ寄せず
        # 端点から半壁厚(60)延長 → y=5572。
        wall = _wall([0.0, 5512.0], [0.0, 4550.0], thickness=120.0)
        columns = [_col(0.0, 5000.0)]
        ext = footing._extend_free_wall_ends([wall], columns)
        assert ext[0]['start'] == [0.0, 5572.0]    # 端点 5512 + 半壁厚 60

    def test_offaxis_column_is_not_used_as_terminal(self) -> None:
        # 壁芯線から半壁厚 + 余裕を超えて外れた柱(側並びの別壁の柱等)は使わない。
        # 120mm 壁(半壁厚 60・余裕 20)・柱が壁芯から 200mm 横 → 端点から延長。
        wall = _wall([0.0, 5512.0], [0.0, 4550.0], thickness=120.0)
        columns = [_col(200.0, 5460.0)]
        ext = footing._extend_free_wall_ends([wall], columns)
        assert ext[0]['start'] == [0.0, 5572.0]    # 端点 5512 + 半壁厚 60

    def test_none_columns_falls_back_to_endpoint_extension(self) -> None:
        # columns 未指定なら従来どおり端点から半壁厚延長する(後方互換)。
        wall = _wall([0.0, 5512.0], [0.0, 4550.0], thickness=120.0)
        ext = footing._extend_free_wall_ends([wall])
        assert ext[0]['start'] == [0.0, 5572.0]


class TestDegenerateGeometryGuards:
    """長さ 0 の壁に対する各ジオメトリ関数のガード(縮退入力の契約)。"""

    def test_connected_collinear_false_for_zero_length(self) -> None:
        a = _wall([0.0, 0.0], [0.0, 0.0])
        b = _wall([0.0, 0.0], [1000.0, 0.0])
        assert footing._walls_connected_collinear(a, b) is False

    def test_intersection_none_for_zero_length(self) -> None:
        a = _wall([0.0, 0.0], [0.0, 0.0])
        b = _wall([0.0, 0.0], [1000.0, 0.0])
        assert footing._wall_intersection(a, b) is None

    def test_point_at_end_true_for_zero_length(self) -> None:
        w = _wall([100.0, 100.0], [100.0, 100.0])
        assert footing._wall_point_at_end(w, 100.0, 100.0) is True

    def test_kept_side_pick_returns_junction_for_zero_length(self) -> None:
        w = _wall([100.0, 100.0], [100.0, 100.0])
        assert footing._kept_side_pick(w, 100.0, 100.0, 120.0) == [100.0, 100.0]


class TestBuildWallJoinCommands:
    """交差する立上り同士の壁結合(JoinWalls)命令を組み立てる。"""

    def test_l_join_at_shared_endpoint(self) -> None:
        # 両端点で交わる直角コーナー → L 結合(2)
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([0.0, 0.0], [0.0, 3000.0]),
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 1
        assert joins[0]['a'] == 0
        assert joins[0]['b'] == 1
        assert joins[0]['join_type'] == footing._JOIN_L
        assert joins[0]['point'] == [0.0, 0.0]
        # 同じ天端高さ同士はコンクリート一体で閉じない
        assert joins[0]['capped'] is False

    def test_pick_points_offset_toward_kept_side(self) -> None:
        # ピック点は交点そのものではなく、各壁の「残す側」(交点から遠い端点方向)へ
        # 寄せた点にする(交点は相手壁芯上にあり残す側が曖昧で VW がコーナーを詰めない)。
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),   # 水平: 残す側は +x 方向
            _wall([0.0, 0.0], [0.0, 3000.0]),   # 鉛直: 残す側は +y 方向
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 1
        join = joins[0]
        # 交点は原点。ピック点はそこから残す側へ寄る。
        assert join['point'] == [0.0, 0.0]
        # a(水平)は +x 方向へ寄り y は変わらない。交点(原点)より離れている。
        assert join['pick_a'][0] > 0.0
        assert join['pick_a'][1] == 0.0
        # b(鉛直)は +y 方向へ寄り x は変わらない。
        assert join['pick_b'][1] > 0.0
        assert join['pick_b'][0] == 0.0
        # 詰める端点(近い側=原点)が最も近い端点のまま(残す側へ寄せすぎない)。
        for pick, wall in ((join['pick_a'], walls[0]), (join['pick_b'], walls[1])):
            px, py = pick
            d_near = math.hypot(px - 0.0, py - 0.0)
            far = wall['end']
            d_far = math.hypot(px - far[0], py - far[1])
            assert d_near < d_far

    def test_overhanging_corner_is_l_not_x(self) -> None:
        # ホームズ君 IFC の外周コーナー: 各壁が相手壁の外面まで伸びるため、壁芯
        # どうしの交点が各壁の端から半壁厚(既定 120mm の半分=60mm)離れる。
        # 固定 1mm 許容では「両方とも内部」= X と誤判定されるが、相手の半壁厚を
        # 含む端点許容で「両方とも端点」= L と正しく判定する。
        walls = [
            _wall([-60.0, 0.0], [3000.0, 0.0]),   # 水平: 左端が縦壁芯を 60mm 越える
            _wall([0.0, -60.0], [0.0, 3000.0]),   # 鉛直: 下端が横壁芯を 60mm 越える
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 1
        assert joins[0]['join_type'] == footing._JOIN_L
        assert joins[0]['point'] == [0.0, 0.0]

    def test_overhanging_t_is_t_not_x(self) -> None:
        # 通し材の途中に、相手の外面まで伸びた材が突き当たる T コーナー。
        # 突き当たる材の端点が通し材の芯を半壁厚越えても T と判定する。
        through = _wall([0.0, 0.0], [3000.0, 0.0])
        stem = _wall([1500.0, -60.0], [1500.0, 2000.0])  # 下端が通し材芯を 60mm 越える
        joins = footing.build_wall_join_commands([through, stem])
        assert len(joins) == 1
        assert joins[0]['join_type'] == footing._JOIN_T
        assert joins[0]['a'] == 1  # stem が先
        assert joins[0]['b'] == 0

    def test_t_join_puts_stem_first(self) -> None:
        # 通し材(内部で交わる)と、その途中に端点で突き当たる材 → T 結合(1)。
        # 延長される stem(端点側)を a に、通し through を b にする。
        through = _wall([0.0, 0.0], [3000.0, 0.0])
        stem = _wall([1500.0, 0.0], [1500.0, 2000.0])
        joins = footing.build_wall_join_commands([through, stem])
        assert len(joins) == 1
        assert joins[0]['join_type'] == footing._JOIN_T
        assert joins[0]['a'] == 1  # stem(index 1)が先
        assert joins[0]['b'] == 0  # through(index 0)が後
        assert joins[0]['point'] == [1500.0, 0.0]
        assert joins[0]['capped'] is False

    def test_x_join_at_interior_crossing(self) -> None:
        # 両方の内部で交わる十字 → X 結合(3)
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([1500.0, -1500.0], [1500.0, 1500.0]),
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 1
        assert joins[0]['join_type'] == footing._JOIN_X
        assert joins[0]['point'] == [1500.0, 0.0]
        assert joins[0]['capped'] is False

    def test_non_touching_walls_not_joined(self) -> None:
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0]),
            _wall([2000.0, 1000.0], [3000.0, 1000.0]),
        ]
        assert footing.build_wall_join_commands(walls) == []

    def test_collinear_walls_not_joined(self) -> None:
        # 同一直線上(平行)は merge の担当。壁結合の対象にしない。
        walls = [
            _wall([0.0, 0.0], [1000.0, 0.0]),
            _wall([2000.0, 0.0], [3000.0, 0.0]),
        ]
        assert footing.build_wall_join_commands(walls) == []

    def test_parallel_offset_walls_not_joined(self) -> None:
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([0.0, 500.0], [3000.0, 500.0]),
        ]
        assert footing.build_wall_join_commands(walls) == []

    def test_different_layer_walls_not_joined(self) -> None:
        a = _wall([0.0, 0.0], [3000.0, 0.0])
        b = _wall([0.0, 0.0], [0.0, 3000.0])
        b['layer'] = '別レイヤ'
        assert footing.build_wall_join_commands([a, b]) == []

    def test_through_wall_with_two_stems_makes_two_joins(self) -> None:
        # 1 本の通し材に 2 本の材が別位置で突き当たる → T 結合が 2 件
        through = _wall([0.0, 0.0], [3000.0, 0.0])
        stem1 = _wall([1000.0, 0.0], [1000.0, 2000.0])
        stem2 = _wall([2000.0, 0.0], [2000.0, 2000.0])
        joins = footing.build_wall_join_commands([through, stem1, stem2])
        assert len(joins) == 2
        assert all(j['join_type'] == footing._JOIN_T for j in joins)
        points = sorted(j['point'][0] for j in joins)
        assert points == [1000.0, 2000.0]

    def test_empty_returns_empty(self) -> None:
        assert footing.build_wall_join_commands([]) == []

    def test_different_height_corner_caps_lower_to_higher(self) -> None:
        # 天端高さの異なる立上りがコーナーで交わる → 低いほうを高いほうに結合し
        # capped=True。低い壁(index 0)が a になる。
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0], top_offset=-540.0),  # 低い
            _wall([0.0, 0.0], [0.0, 3000.0], top_offset=-190.0),  # 高い
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 1
        assert joins[0]['capped'] is True
        assert joins[0]['a'] == 0  # 低いほうが a(高いほうへ結合)
        assert joins[0]['b'] == 1

    def test_different_height_t_caps_stem(self) -> None:
        # 低い立上りが高い通し材の側面に突き当たる T → 端部を閉じる(capped=True)
        through = _wall([0.0, 0.0], [3000.0, 0.0], top_offset=-190.0)  # 高い通し
        stem = _wall([1500.0, 0.0], [1500.0, 2000.0], top_offset=-540.0)  # 低い
        joins = footing.build_wall_join_commands([through, stem])
        assert len(joins) == 1
        assert joins[0]['join_type'] == footing._JOIN_T
        assert joins[0]['a'] == 1  # stem(低い側)が a
        assert joins[0]['b'] == 0
        assert joins[0]['capped'] is True

    def test_three_walls_at_endpoint_first_two_l_rest_t(self) -> None:
        # 3 本の立上りが 1 点で端点を突き合わせる → はじめの 2 本を L、残りを T
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0]),
            _wall([0.0, 0.0], [0.0, 3000.0]),
            _wall([0.0, 0.0], [3000.0, 3000.0]),
        ]
        joins = footing.build_wall_join_commands(walls)
        # 3 本 → 結合は 2 件(スパニングツリー)。全ペア 3 件にはしない。
        assert len(joins) == 2
        assert sorted(j['join_type'] for j in joins) == [
            footing._JOIN_T, footing._JOIN_L]  # T=1, L=2
        corner = next(j for j in joins if j['join_type'] == footing._JOIN_L)
        assert {corner['a'], corner['b']} == {0, 1}  # はじめの 2 本を L
        butt = next(j for j in joins if j['join_type'] == footing._JOIN_T)
        assert butt['a'] == 2  # 3 本目を T で突き当てる
        assert all(j['capped'] is False for j in joins)  # 同一高さ

    def test_three_walls_crossing_high_uncapped_first_then_capped(self) -> None:
        # 3 本が 1 点で内部交差(交点)。天端が最も高い 2 本を capped=False で先に
        # 繋ぎ、低い 1 本を capped=True で繋ぐ。
        walls = [
            _wall([0.0, 0.0], [3000.0, 0.0], top_offset=-190.0),        # 高い(通し)
            _wall([1500.0, -1500.0], [1500.0, 1500.0], top_offset=-190.0),  # 高い(通し)
            _wall([0.0, -1500.0], [3000.0, 1500.0], top_offset=-540.0),  # 低い(通し)
        ]
        joins = footing.build_wall_join_commands(walls)
        assert len(joins) == 2
        # capped=False(高い立上り同士)が先、capped=True(低い立上り)が後
        assert joins[0]['capped'] is False
        assert {joins[0]['a'], joins[0]['b']} == {0, 1}
        assert joins[1]['capped'] is True
        assert joins[1]['a'] == 2  # 低いほうが a(高いほうへ結合)


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
