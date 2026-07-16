"""解析フェーズ (ifc.rafter) のテスト。

屋根面のクリップ・配置間隔・勾配計算(``_rafters_for_plane``)は合成入力で、
命令組み立ては実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import open_ifc, rafter
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import CLASS_TARUKI

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestRaftersForPlane:
    # 平面: XY 平面上の 4m×3m 矩形が、+Y 方向に立ち上がる片流れ屋根。
    # 軒(y=0)で z=1000、棟(y=3000)で z=2000。勾配は Y 方向のみ。
    # 法線 = (0, -1, 3)/√10 を正規化(上向き)。単位法線を直接与える。
    #   z(x, y) = 1000 + (2000-1000)/3000 * y = 1000 + y/3
    #   => 平面: z = 1000 + y/3 ⇒ 法線 ∝ (0, -1/3, 1) ⇒ (0, -1, 3)/√10
    NX, NY, NZ = 0.0, -1.0 / math.sqrt(10.0), 3.0 / math.sqrt(10.0)
    VERTS = [
        (0.0, 0.0, 1000.0),
        (4000.0, 0.0, 1000.0),
        (4000.0, 3000.0, 2000.0),
        (0.0, 3000.0, 2000.0),
    ]

    def _rafters(self) -> list:
        return rafter._rafters_for_plane(
            self.VERTS, (self.NX, self.NY, self.NZ),
            'R-垂木', storey_elevation=0.0, center_x=0.0, center_y=0.0)

    def test_rafters_at_both_ends_interior_455(self) -> None:
        rafters = self._rafters()
        # 掃引方向は X(軒に平行)。幅 4000mm。両端(x≈0, x≈4000)に必ず 1 本、
        # 内部は 455 以下(中間は 455 ちょうど・端数は両端へ寄せる)。
        # n=ceil(4000/455)=9 → 垂木 n+1=10 本。
        assert len(rafters) == 10
        xs = sorted(r['start'][0] for r in rafters)
        # 屋根の両端に垂木がある(端の掃引線は退化回避で _EDGE_TOL=1mm 内側)。
        assert xs[0] <= 1.0 + 1e-6
        assert xs[-1] >= 4000.0 - 1.0 - 1e-6
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        # すべて 455 以下、中間の間隔は 455 ちょうど
        assert max(gaps) <= 455.0 + 1e-6
        assert any(math.isclose(g, 455.0, abs_tol=1e-6) for g in gaps)
        # 端数は両端の 2 区間へ等分(左右対称)
        assert math.isclose(gaps[0], gaps[-1], abs_tol=1e-6)

    def test_rafters_run_up_slope_start_low_end_high(self) -> None:
        for r in self._rafters():
            # start=軒側(y=0, z=1000), end=棟側(y=3000, z=2000)
            assert math.isclose(r['start'][1], 0.0, abs_tol=1e-6)
            assert math.isclose(r['end'][1], 3000.0, abs_tol=1e-6)
            assert r['end_elevation'] > r['elevation']
            assert math.isclose(r['elevation'], 1000.0, abs_tol=1e-6)
            assert math.isclose(r['end_elevation'], 2000.0, abs_tol=1e-6)

    def test_default_section_and_class(self) -> None:
        r = self._rafters()[0]
        assert r['width'] == 45.0
        assert r['height'] == 45.0
        assert r['class'] == CLASS_TARUKI
        assert r['layer'] == 'R-垂木'

    def test_storey_elevation_added_to_z(self) -> None:
        rafters = rafter._rafters_for_plane(
            self.VERTS, (self.NX, self.NY, self.NZ),
            'R-垂木', storey_elevation=6300.0, center_x=0.0, center_y=0.0)
        r = rafters[0]
        assert math.isclose(r['elevation'], 1000.0 + 6300.0, abs_tol=1e-6)
        assert math.isclose(r['end_elevation'], 2000.0 + 6300.0, abs_tol=1e-6)

    def test_center_offset_subtracted_from_xy(self) -> None:
        rafters = rafter._rafters_for_plane(
            self.VERTS, (self.NX, self.NY, self.NZ),
            'R-垂木', storey_elevation=0.0, center_x=100.0, center_y=200.0)
        r = rafters[0]
        assert math.isclose(r['start'][1], 0.0 - 200.0, abs_tol=1e-6)
        assert math.isclose(r['end'][1], 3000.0 - 200.0, abs_tol=1e-6)

    def test_flat_plane_has_no_rafters(self) -> None:
        # ほぼ水平な面(法線がほぼ +Z)は勾配方向が定まらないため垂木なし
        flat = [(0.0, 0.0, 0.0), (4000.0, 0.0, 0.0),
                (4000.0, 3000.0, 0.0), (0.0, 3000.0, 0.0)]
        assert rafter._rafters_for_plane(
            flat, (0.0, 0.0, 1.0), 'R-垂木', 0.0, 0.0, 0.0) == []


class TestSweepPositions:
    """``_sweep_positions``: 両端 + 内部 455 以下・中間 455・端数両端。"""

    def test_ends_included_and_clamped_inward(self) -> None:
        pos = rafter._sweep_positions(0.0, 2000.0, 455.0)
        # 両端は _EDGE_TOL(1mm)だけ内側へ寄る
        assert math.isclose(pos[0], 1.0, abs_tol=1e-6)
        assert math.isclose(pos[-1], 1999.0, abs_tol=1e-6)

    def test_interior_gaps_are_module(self) -> None:
        # 幅 2000 / 455 → n=ceil=5 区間、中間 3 区間は 455 ちょうど
        pos = rafter._sweep_positions(0.0, 2000.0, 455.0)
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        # 中間 3 区間 = 455、両端はクランプ分 1mm を除いた端数
        assert sum(1 for g in gaps if math.isclose(g, 455.0, abs_tol=1e-6)) == 3
        assert max(gaps) <= 455.0 + 1e-6

    def test_exact_multiple_uniform(self) -> None:
        pos = rafter._sweep_positions(0.0, 1820.0, 455.0)
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        # 端 2 区間はクランプで 454、中間 2 区間は 455
        assert len(pos) == 5
        assert sum(1 for g in gaps if math.isclose(g, 455.0, abs_tol=1e-6)) == 2


class TestBuildRafterCommands:
    def test_empty_ifc_returns_empty(self) -> None:
        assert rafter.build_rafter_commands(ifcopenshell.file()) == []

    def test_fixture_rafters_are_valid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        rafters = rafter.build_rafter_commands(ifc)
        assert len(rafters) > 0
        for r in rafters:
            # すべて既定断面・垂木クラス、棟が軒より高い
            assert r['width'] == 45.0 and r['height'] == 45.0
            assert r['class'] == CLASS_TARUKI
            assert r['end_elevation'] >= r['elevation']
            assert r['layer'].endswith('-垂木')

    def test_fixture_layers_map_to_roof_storeys(self) -> None:
        # 伏図次郎: 下屋根(2FL)→ 2-垂木、主屋根(RFL)→ R-垂木
        ifc = _open('伏図次郎【2階】.ifc')
        layers = {r['layer'] for r in rafter.build_rafter_commands(ifc)}
        assert layers == {'2-垂木', 'R-垂木'}

    def test_shed_dormer_without_moya_still_gets_rafters(self) -> None:
        # スキップフロア: 2FL の下屋根は母屋を持たないが屋根版=垂木を持つ
        ifc = _open('スキップフロア_サンプル.ifc')
        layers = {r['layer'] for r in rafter.build_rafter_commands(ifc)}
        assert '2-垂木' in layers
