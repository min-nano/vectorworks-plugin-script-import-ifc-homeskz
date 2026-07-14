"""解析フェーズ (ifc.fire_brace) のテスト。

ジオメトリ計算(端面の識別・交点・回転角)は合成入力で、命令組み立ては
実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import fire_brace, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestSegmentIntersection:
    def test_perpendicular_lines(self) -> None:
        # y=1 の水平線分と x=2 の鉛直線分の交点は (2, 1)
        p = fire_brace._segment_intersection(
            ((0.0, 1.0), (5.0, 1.0)), ((2.0, -3.0), (2.0, 4.0)))
        assert p is not None
        assert math.isclose(p[0], 2.0)
        assert math.isclose(p[1], 1.0)

    def test_parallel_lines_return_none(self) -> None:
        assert fire_brace._segment_intersection(
            ((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0))) is None


class TestEndFacesAndBasePoint:
    # 中心線 v=0 に対称な footprint(長辺 v=±5、端面が v をまたぐ)。
    # world 座標は簡単のため局所座標と一致させる。
    LOCAL = [(0.0, -5.0), (0.0, 5.0), (10.0, 5.0), (12.0, -5.0)]
    WORLD = [(0.0, -5.0), (0.0, 5.0), (10.0, 5.0), (12.0, -5.0)]

    def test_end_faces_are_the_v_crossing_edges(self) -> None:
        faces = fire_brace._end_faces(self.WORLD, self.LOCAL)
        # 端面は v の符号が始終点で反転する辺(P0-P1 と P2-P3)
        assert len(faces) == 2
        assert faces[0] == ((0.0, -5.0), (0.0, 5.0))
        assert faces[1] == ((10.0, 5.0), (12.0, -5.0))

    def test_base_point_is_end_face_intersection(self) -> None:
        faces = fire_brace._end_faces(self.WORLD, self.LOCAL)
        base = fire_brace._base_point(faces)
        assert base is not None
        # 端面1(x=0)と端面2(P2-P3 を延長)の交点。P2-P3 は y=5→-5 で x=10→12、
        # x=0 では y = 5 + (0-10)/(12-10)*(-10) = 55
        assert math.isclose(base[0], 0.0)
        assert math.isclose(base[1], 55.0)

    def test_base_point_requires_exactly_two_faces(self) -> None:
        assert fire_brace._base_point([]) is None
        assert fire_brace._base_point(
            [((0.0, 0.0), (1.0, 1.0))]) is None


class TestAngle:
    def test_points_from_base_to_centroid_with_offset(self) -> None:
        # 基準点 (0,0)、重心が (+1,-1) 方向 = 二等分方向 -45 度。シンボルの基準姿勢
        # 補正(反時計方向 45 度)を加えて 0 度になる。
        world = [(2.0, -2.0), (2.0, -2.0), (2.0, -2.0), (2.0, -2.0)]
        angle = fire_brace._angle((0.0, 0.0), world)
        assert math.isclose(angle, 0.0, abs_tol=1e-9)

    def test_applies_symbol_angle_offset(self) -> None:
        # 二等分方向が 0 度(重心が +X 方向)なら補正後は 45 度
        world = [(2.0, 0.0), (2.0, 0.0), (2.0, 0.0), (2.0, 0.0)]
        angle = fire_brace._angle((0.0, 0.0), world)
        assert math.isclose(angle, 45.0)


class TestIsFireBrace:
    def test_matches_beam_named_fire_brace(self) -> None:
        ifc = ifcopenshell.file()
        e = ifc.create_entity('IfcMember', Name='火打:1_1')
        assert fire_brace._is_fire_brace(e)

    def test_ignores_other_beams(self) -> None:
        ifc = ifcopenshell.file()
        e = ifc.create_entity('IfcBeam', Name='木梁:土台:1')
        assert not fire_brace._is_fire_brace(e)

    def test_ignores_non_beam_named_fire_brace(self) -> None:
        ifc = ifcopenshell.file()
        e = ifc.create_entity('IfcColumn', Name='火打:1_1')
        assert not fire_brace._is_fire_brace(e)


class TestBuildFromFixture:
    FILENAME = '伏図次郎【2階】.ifc'

    def test_command_shape(self) -> None:
        ifc = _open(self.FILENAME)
        braces = fire_brace.build_fire_brace_commands(ifc)
        assert braces
        for brace in braces:
            assert brace['symbol'] == '鋼製火打'
            # 火打は横架材レイヤ(横架材天端 / 最上階は軒高)に置く
            assert brace['layer'].endswith('横架材天端') or brace['layer'].endswith('軒高')
            assert len(brace['position']) == 2
            assert isinstance(brace['angle'], float)

    def test_count_matches(self) -> None:
        ifc = _open(self.FILENAME)
        braces = fire_brace.build_fire_brace_commands(ifc)
        assert len(braces) == 28

    def test_positions_are_centered(self) -> None:
        ifc = _open(self.FILENAME)
        braces = fire_brace.build_fire_brace_commands(ifc)
        # グリッド中心オフセット補正済みなら XY は 0 を中心に分布する
        xs = [b['position'][0] for b in braces]
        ys = [b['position'][1] for b in braces]
        assert min(xs) < 0 < max(xs)
        assert min(ys) < 0 < max(ys)

    def test_top_story_uses_eaves_layer(self) -> None:
        ifc = _open(self.FILENAME)
        braces = fire_brace.build_fire_brace_commands(ifc)
        # 最上階(屋根)の火打は軒高レイヤに配置される
        assert any(b['layer'].endswith('軒高') for b in braces)

    def test_all_fixtures_build_without_error(self) -> None:
        for filename in (
            'サンプル1 (住木邸新築工事).ifc',
            'スキップフロア_サンプル.ifc',
            'グレー本モデルプラン1【3階】.ifc',
            'グレー本モデルプラン2【3階】.ifc',
        ):
            ifc = _open(filename)
            braces = fire_brace.build_fire_brace_commands(ifc)
            assert braces
            for brace in braces:
                assert brace['symbol'] == '鋼製火打'
