"""解析フェーズ (ifc.rebar) のテスト。

配筋仕様のパース・断面ジオメトリの補助関数は手書きの入力で、命令組み立ては実 IFC
フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

from vectorworks_plugin_import_ifc_homeskz.ifc import rebar
from vectorworks_plugin_import_ifc_homeskz.ifc.loader import open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


class TestStripGrade:
    def test_strips_underscore_grade(self) -> None:
        assert rebar._strip_grade('SD295_1-D13') == '1-D13'

    def test_strips_hyphen_grade(self) -> None:
        assert rebar._strip_grade('SD295-D13@200') == 'D13@200'

    def test_keeps_slab_direction_separator(self) -> None:
        # 鋼種だけ落とし、方向区切りの '_' は残す
        assert rebar._strip_grade('SD295_D13@300_D13@300') == 'D13@300_D13@300'

    def test_leaves_count_prefixed_value(self) -> None:
        # 数字始まり(本数)は鋼種でないため触らない
        assert rebar._strip_grade('2-D13') == '2-D13'

    def test_leaves_plain_spec(self) -> None:
        assert rebar._strip_grade('D13@150') == 'D13@150'

    def test_empty_stays_empty(self) -> None:
        assert rebar._strip_grade('') == ''


class TestStripCountPrefix:
    def test_strips_count(self) -> None:
        assert rebar._strip_count_prefix('1-D10@300') == 'D10@300'

    def test_leaves_pitch_spec(self) -> None:
        assert rebar._strip_count_prefix('D10@300') == 'D10@300'


class TestSlabDirs:
    def test_two_directions(self) -> None:
        assert rebar._slab_dirs('SD295_D13@175_D13@200') == ('D13@175', 'D13@200')

    def test_single_direction_duplicates(self) -> None:
        assert rebar._slab_dirs('SD295-D13@200') == ('D13@200', 'D13@200')

    def test_empty_is_none(self) -> None:
        assert rebar._slab_dirs('') is None


class TestBeamBars:
    def test_uses_ifc_values(self) -> None:
        reinf = {'TopReinforce': 'SD295_1-D13', 'BottomReinforce': 'SD295_2-D13',
                 'ShearReinforce': 'SD295_1-D10@300'}
        assert rebar._beam_bars(reinf) == ('1-D13', '2-D13', 'D10@300')

    def test_falls_back_to_defaults_when_absent(self) -> None:
        # IFC に配筋情報が無い場合はユーザー指定の既定値
        assert rebar._beam_bars({}) == ('1-D13', '1-D13', 'D10@250')


class TestSlabBars:
    def test_uses_ifc_values(self) -> None:
        reinf = {'TopReinforce': 'SD295_D13@300_D13@300'}
        assert rebar._slab_bars(reinf) == ('D13@300', 'D13@300')

    def test_falls_back_to_defaults_when_absent(self) -> None:
        assert rebar._slab_bars({}) == ('D13@150', 'D13@150')


class TestBeamGeometry:
    def test_rectangle_centerline_through_origin(self) -> None:
        # 立上り(矩形・原点中心): u 範囲が対称なので中心線は配置原点を通る。
        # 局所 X=世界 Y(幅方向)、押し出し=世界 X、断面 幅 120・高さ 500。
        pl = ((1000.0, 2000.0, -100.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
              (1.0, 0.0, 0.0))
        pts = [(-60.0, 0.0), (60.0, 0.0), (60.0, 500.0), (-60.0, 500.0)]
        solid = (pl, (1.0, 0.0, 0.0), 3000.0, pts, (120.0, 500.0))
        result = rebar._beam_geometry(solid, 0.0, 0.0)
        assert result is not None
        start, end, width, height, top = result
        assert math.isclose(width, 120.0)
        assert math.isclose(height, 500.0)
        # u_mid=0 → 中心線は原点、押し出し方向(世界 X)へ 3000
        assert start == [1000.0, 2000.0]
        assert end == [4000.0, 2000.0]
        assert math.isclose(top, 400.0)

    def test_trapezoid_uses_bounding_box_and_offset_centerline(self) -> None:
        # 地中梁(任意断面): u 範囲が非対称なので中心線が u 中点だけずれる。
        # 局所 X=世界 Y、押し出し=世界 X。u: -290..0(幅 290、中点 -145)、v: 0..140。
        pl = ((0.0, 0.0, -240.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
              (1.0, 0.0, 0.0))
        pts = [(0.0, 0.0), (-150.0, 0.0), (-290.0, 140.0), (0.0, 140.0)]
        solid = (pl, (1.0, 0.0, 0.0), 1060.0, pts, None)
        result = rebar._beam_geometry(solid, 0.0, 0.0)
        assert result is not None
        start, end, width, height, top = result
        assert math.isclose(width, 290.0)
        assert math.isclose(height, 140.0)
        # u_mid=-145 を局所 X=(0,1,0) 方向へ → 世界 Y=-145
        assert math.isclose(start[0], 0.0)
        assert math.isclose(start[1], -145.0)
        assert math.isclose(end[0], 1060.0)
        assert math.isclose(top, -100.0)

    def test_degenerate_returns_none(self) -> None:
        pl = ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
        # 幅 0(全点同一 u)
        pts = [(0.0, 0.0), (0.0, 500.0)]
        solid = (pl, (1.0, 0.0, 0.0), 3000.0, pts, None)
        assert rebar._beam_geometry(solid, 0.0, 0.0) is None


class TestBuildRebarCommands:
    def _document(self) -> list[rebar.RebarCommand]:
        ifc = open_ifc(os.path.join(FIXTURES_DIR, 'サンプル1 (住木邸新築工事).ifc'))
        return rebar.build_rebar_commands(ifc)

    def test_produces_beam_and_slab_commands(self) -> None:
        commands = self._document()
        modes = {c['mode'] for c in commands}
        assert modes == {'beam', 'slab'}

    def test_walls_on_wall_layer_beam_mode(self) -> None:
        commands = self._document()
        wall_rebars = [c for c in commands if c['layer'] == 'F-立上り']
        assert wall_rebars
        for command in wall_rebars:
            assert command['mode'] == 'beam'
            assert command['closed'] is False
            assert len(command['path']) == 2
            assert command['section_size']
            assert command['top_bars'] and command['bottom_bars']
            assert command['stirrup']

    def test_slabs_are_closed_slab_mode(self) -> None:
        commands = self._document()
        slab_rebars = [c for c in commands if c['mode'] == 'slab']
        assert slab_rebars
        for command in slab_rebars:
            assert command['layer'] == 'F-底盤'
            assert command['closed'] is True
            assert len(command['path']) >= 3
            assert command['main_bar'] and command['dist_bar']
            assert command['slab_thickness'] > 0

    def test_ground_beams_placed_on_slab_layer_as_beam(self) -> None:
        # 地中梁は F-底盤 レイヤに梁モードで置く
        commands = self._document()
        beam_on_slab = [c for c in commands
                        if c['layer'] == 'F-底盤' and c['mode'] == 'beam']
        assert beam_on_slab

    def test_reinforcement_class_assigned(self) -> None:
        commands = self._document()
        assert all(c['class'] == rebar.CLASS_REBAR for c in commands)

    def test_path_z_is_absolute_top(self) -> None:
        # 梁モードのパス Z は断面天端(始終点で一致)
        commands = self._document()
        for command in commands:
            if command['mode'] == 'beam':
                z0 = command['path'][0][2]
                assert all(math.isclose(v[2], z0) for v in command['path'])
