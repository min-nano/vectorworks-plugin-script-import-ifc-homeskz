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
        # 掃引方向は X(軒に平行)。幅 4000mm。両端の垂木は屋根面の端から垂木幅の
        # 半分(22.5mm)だけ内側、内部は 455 以下(中間は 455 ちょうど・端数は両端へ
        # 寄せる)。実効幅 (4000 - 45)=3955 / 455 → n=ceil=9 → 垂木 n+1=10 本。
        assert len(rafters) == 10
        xs = sorted(r['start'][0] for r in rafters)
        # 両端の垂木は屋根面の端から半幅(22.5mm)内側にある(はみ出さない)。
        assert math.isclose(xs[0], 22.5, abs_tol=1e-6)
        assert math.isclose(xs[-1], 4000.0 - 22.5, abs_tol=1e-6)
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

    def test_tiny_face_below_min_length_has_no_rafters(self) -> None:
        # 掃引方向の広がりが _MIN_RAFTER_LENGTH(100mm)未満の極小面は垂木なし
        tiny = [(0.0, 0.0, 1000.0), (50.0, 0.0, 1000.0),
                (50.0, 3000.0, 2000.0), (0.0, 3000.0, 2000.0)]
        assert rafter._rafters_for_plane(
            tiny, (self.NX, self.NY, self.NZ), 'R-垂木', 0.0, 0.0, 0.0) == []

    def test_non_convex_face_splits_into_multiple_segments(self) -> None:
        # ドーマ状の非凸面(左辺中央に矩形の切り欠き)。掃引 X の切り欠き範囲では
        # 走査線が 4 交点になり、1 掃引線が 2 本の垂木に分割される。
        # 平面 z=1000+y/3(TestRaftersForPlane と同じ勾配)。
        def z(y: float) -> float:
            return 1000.0 + y / 3.0
        notched = [
            (0.0, 0.0, z(0.0)), (4000.0, 0.0, z(0.0)),
            (4000.0, 3000.0, z(3000.0)), (0.0, 3000.0, z(3000.0)),
            (0.0, 2000.0, z(2000.0)), (2000.0, 2000.0, z(2000.0)),
            (2000.0, 1000.0, z(1000.0)), (0.0, 1000.0, z(1000.0)),
        ]
        rafters = rafter._rafters_for_plane(
            notched, (self.NX, self.NY, self.NZ), 'R-垂木', 0.0, 0.0, 0.0)

        def has(seg_lo: float, seg_hi: float) -> bool:
            # start=軒側(低 y), end=棟側(高 y)
            return any(math.isclose(r['start'][1], seg_lo, abs_tol=1.0)
                       and math.isclose(r['end'][1], seg_hi, abs_tol=1.0)
                       for r in rafters)

        # 切り欠き範囲(x<2000)では下 [0,1000] と上 [2000,3000] の 2 区間に分割
        assert has(0.0, 1000.0)
        assert has(2000.0, 3000.0)
        # 切り欠きの無い範囲(x>2000)では全長 [0,3000] の 1 本
        assert has(0.0, 3000.0)


class TestSweepPositions:
    """``_sweep_positions``: 両端は半幅内側 + 内部 455 以下・中間 455・端数両端。"""

    def test_ends_inset_by_half_width(self) -> None:
        # 両端の垂木は屋根面の端から inset(=垂木幅の半分=22.5mm)だけ内側へ寄る
        pos = rafter._sweep_positions(0.0, 2000.0, 455.0, 22.5)
        assert math.isclose(pos[0], 22.5, abs_tol=1e-6)
        assert math.isclose(pos[-1], 2000.0 - 22.5, abs_tol=1e-6)

    def test_interior_gaps_are_module(self) -> None:
        # 実効幅 (2000 - 2*22.5)=1955 / 455 → n=ceil=5 区間、中間 3 区間は 455
        pos = rafter._sweep_positions(0.0, 2000.0, 455.0, 22.5)
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        assert sum(1 for g in gaps if math.isclose(g, 455.0, abs_tol=1e-6)) == 3
        assert max(gaps) <= 455.0 + 1e-6

    def test_end_gaps_split_remainder(self) -> None:
        pos = rafter._sweep_positions(0.0, 1820.0, 455.0, 22.5)
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        # 実効幅 (1820 - 45)=1775 / 455 → n=ceil=4 区間、中間 2 区間は 455、
        # 端数を両端へ等分するため両端の区間は等しい
        assert len(pos) == 5
        assert sum(1 for g in gaps if math.isclose(g, 455.0, abs_tol=1e-6)) == 2
        assert math.isclose(gaps[0], gaps[-1], abs_tol=1e-6)

    def test_width_within_interval_two_ends_only(self) -> None:
        # 実効幅 <= interval は内部無しで両端の 2 本のみ(いずれも半幅内側)
        pos = rafter._sweep_positions(0.0, 400.0, 455.0, 22.5)
        assert len(pos) == 2
        assert math.isclose(pos[0], 22.5, abs_tol=1e-6)
        assert math.isclose(pos[-1], 400.0 - 22.5, abs_tol=1e-6)

    def test_degenerate_width_single_center(self) -> None:
        # 半幅を差し引くと広がりが極小(屋根が垂木幅程度に狭い)なら中央 1 本
        pos = rafter._sweep_positions(1000.0, 1030.0, 455.0, 22.5)
        assert pos == [1015.0]


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
