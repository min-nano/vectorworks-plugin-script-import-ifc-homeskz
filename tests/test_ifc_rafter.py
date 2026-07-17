"""解析フェーズ (ifc.rafter) のテスト。

屋根面のクリップ・配置間隔・勾配計算(``_rafters_for_plane``)は合成入力で、
命令組み立ては実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
from typing import cast

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    MemberCommand,
    StoryBoundCommand,
)
from vectorworks_plugin_import_ifc_homeskz.ifc import rafter
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import CLASS_TARUKI

from tests.conftest import load_fixture_ifc


def _open(filename: str) -> ifcopenshell.file:
    return load_fixture_ifc(filename)


def _girder(start: list[float], end: list[float], width: float) -> MemberCommand:
    """桁幅参照テスト用の軒桁 member 命令(_girder_width_at は start/end/width のみ参照)。"""
    bound: StoryBoundCommand = {'story_offset': 0, 'level': '軒高', 'offset': 0.0}
    return {
        'layer': 'R-軒高', 'member_id': '', 'class': CLASS_TARUKI,
        'start': start, 'end': end, 'width': width, 'height': 180.0,
        'elevation': 0.0, 'end_elevation': 0.0,
        'start_bound': bound, 'end_bound': bound,
    }


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


class TestRafterSupportPoint:
    """支持点(start=屋根面と横架材天端 Z の交点)・軒の出・差し込み・ラベル。

    平面は ``TestRaftersForPlane`` と同じ z=1000+y/3(軒 y=0 で z=1000、棟 y=3000
    で z=2000)。
    """
    NX, NY, NZ = TestRaftersForPlane.NX, TestRaftersForPlane.NY, TestRaftersForPlane.NZ
    VERTS = TestRaftersForPlane.VERTS

    def _rafters(
        self, beam_top_z: float, members: list[MemberCommand] | None = None,
    ) -> list:
        return rafter._rafters_for_plane(
            self.VERTS, (self.NX, self.NY, self.NZ), 'R-垂木',
            storey_elevation=0.0, center_x=0.0, center_y=0.0,
            beam_top_z=beam_top_z, story_members=members or [])

    def test_start_is_intersection_with_beam_top_z(self) -> None:
        # beam_top_z=1500 → 屋根面と交わる支持点は y=1500(z=1500)。軒先(y=0)より上。
        for r in self._rafters(1500.0):
            assert math.isclose(r['start'][1], 1500.0, abs_tol=1e-6)
            assert math.isclose(r['elevation'], 1500.0, abs_tol=1e-6)
            # 棟側(end)は変わらず y=3000, z=2000
            assert math.isclose(r['end'][1], 3000.0, abs_tol=1e-6)
            assert math.isclose(r['end_elevation'], 2000.0, abs_tol=1e-6)

    def test_overhang_is_support_to_tip_minus_embedment(self) -> None:
        # 壁外面から軒先の距離 = 支持点(y=1500)→軒先(y=0)の水平距離(1500)から
        # 支持部分の差し込み(既定桁幅/2=52.5)を引いた残り。
        expected = 1500.0 - rafter.DEFAULT_GIRDER_WIDTH / 2.0
        for r in self._rafters(1500.0):
            assert math.isclose(r['overhang'], expected, abs_tol=1e-6)
            # 差し込み + 軒の出 = 支持点→軒先(VW は軒先をこの和の位置に置く)
            assert math.isclose(
                r['embedment'] + r['overhang'], 1500.0, abs_tol=1e-6)

    def test_overhang_subtracts_referenced_girder_half_width(self) -> None:
        # 桁幅を参照した場合も 差し込み(桁幅/2)+ 軒の出 = 支持点→軒先 を保つ
        girder = _girder([-1000.0, 1500.0], [5000.0, 1500.0], 120.0)
        for r in self._rafters(1500.0, [girder]):
            assert math.isclose(r['embedment'], 60.0, abs_tol=1e-6)
            assert math.isclose(r['overhang'], 1500.0 - 60.0, abs_tol=1e-6)

    def test_no_overhang_when_beam_top_at_or_below_eave_tip(self) -> None:
        # beam_top_z <= 軒先 z(1000) なら支持点は取れず start=軒先・overhang=0
        for r in self._rafters(800.0):
            assert math.isclose(r['start'][1], 0.0, abs_tol=1e-6)
            assert math.isclose(r['elevation'], 1000.0, abs_tol=1e-6)
            assert r['overhang'] == 0.0

    def test_embedment_defaults_to_half_default_girder(self) -> None:
        # 桁幅参照なし(story_members 空)→ 差し込み = 既定桁幅/2
        for r in self._rafters(1500.0):
            assert math.isclose(
                r['embedment'], rafter.DEFAULT_GIRDER_WIDTH / 2.0, abs_tol=1e-6)

    def test_embedment_uses_referenced_girder_half_width(self) -> None:
        # 支持点(y=1500)の真下に X 方向(垂木に直交)の軒桁 幅120 → 差し込み 60
        girder = _girder([-1000.0, 1500.0], [5000.0, 1500.0], 120.0)
        rafters = self._rafters(1500.0, [girder])
        assert rafters
        for r in rafters:
            assert math.isclose(r['embedment'], 60.0, abs_tol=1e-6)

    def test_parallel_member_not_used_as_girder(self) -> None:
        # 垂木と平行に走る材(Y 方向)は軒桁とみなさない → 既定桁幅にフォールバック
        parallel = _girder([0.0, -1000.0], [0.0, 5000.0], 120.0)
        for r in self._rafters(1500.0, [parallel]):
            assert math.isclose(
                r['embedment'], rafter.DEFAULT_GIRDER_WIDTH / 2.0, abs_tol=1e-6)

    def test_label_shows_spec(self) -> None:
        for r in self._rafters(1500.0):
            assert r['label'] == '45×45@455'


class TestGirderWidthAt:
    """``_girder_width_at``: 支持点の真下の軒桁(横架材命令)の幅参照。

    垂木の方向は +Y(支持点→棟)とし、X 方向に走る材が軒桁(垂木に直交)になる。
    """
    # 支持点(原点)・垂木方向(+Y)
    PX, PY, RDX, RDY = 0.0, 0.0, 0.0, 1000.0

    def _w(self, members: list[MemberCommand]) -> float:
        return rafter._girder_width_at(self.PX, self.PY, self.RDX, self.RDY, members)

    def test_returns_default_when_no_members(self) -> None:
        assert self._w([]) == rafter.DEFAULT_GIRDER_WIDTH

    def test_returns_half_width_perpendicular_member_under_point(self) -> None:
        # 支持点の真上を通る X 方向(垂木に直交)の軒桁 幅150 → 150 を返す
        girder = _girder([-1000.0, 0.0], [1000.0, 0.0], 150.0)
        assert math.isclose(self._w([girder]), 150.0, abs_tol=1e-6)

    def test_skips_zero_length_member(self) -> None:
        # 始終点が同じ退化した材(mlen=0)は無視して既定桁幅にフォールバックする
        degenerate = _girder([0.0, 0.0], [0.0, 0.0], 150.0)
        assert self._w([degenerate]) == rafter.DEFAULT_GIRDER_WIDTH

    def test_skips_member_beyond_perpendicular_tolerance(self) -> None:
        # 芯線が支持点から直交距離 _GIRDER_SEARCH_TOL より遠い材は採らない
        far = rafter._GIRDER_SEARCH_TOL + 10.0
        girder = _girder([-1000.0, far], [1000.0, far], 150.0)
        assert self._w([girder]) == rafter.DEFAULT_GIRDER_WIDTH

    def test_skips_member_when_point_outside_axis_span(self) -> None:
        # 支持点が芯線区間の外(射影 t が区間外)なら採らない
        girder = _girder([500.0, 0.0], [2000.0, 0.0], 150.0)
        assert self._w([girder]) == rafter.DEFAULT_GIRDER_WIDTH

    def test_picks_nearest_of_multiple_girders(self) -> None:
        # 直交距離が最も近い軒桁の幅を採る(遠い方は採らない)
        near = _girder([-1000.0, 10.0], [1000.0, 10.0], 150.0)
        far = _girder([-1000.0, 80.0], [1000.0, 80.0], 200.0)
        assert math.isclose(self._w([far, near]), 150.0, abs_tol=1e-6)


class TestRoofPlaneEdgeCases:
    """``_roof_plane`` / ``build_rafter_commands`` の縮退・スキップ経路。"""

    def test_roof_plane_none_when_solid_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ソリッドが取得できない屋根版は None(垂木を導出しない)
        monkeypatch.setattr(rafter, '_world_solid', lambda e: None)
        assert rafter._roof_plane(
            cast(ifcopenshell.entity_instance, object())) is None

    def test_roof_plane_none_when_fewer_than_three_points(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 平面外形の頂点が 3 点未満の屋根版は None
        placement = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                     (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        solid = (placement, None, 0.0, [(0.0, 0.0), (1.0, 0.0)], None)
        monkeypatch.setattr(rafter, '_world_solid', lambda e: solid)
        assert rafter._roof_plane(
            cast(ifcopenshell.entity_instance, object())) is None

    def test_build_skips_roof_slab_without_plane(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 屋根版はあるが平面が取れない場合、その要素は飛ばして空リストになる
        ifc = _open('伏図次郎【2階】.ifc')
        monkeypatch.setattr(rafter, '_roof_plane', lambda e: None)
        assert rafter.build_rafter_commands(ifc) == []


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
            # すべて既定断面・垂木クラス、棟が軒(支持点)より高い
            assert r['width'] == 45.0 and r['height'] == 45.0
            assert r['class'] == CLASS_TARUKI
            assert r['end_elevation'] >= r['elevation']
            assert r['layer'].endswith('-垂木')
            # 軒の出は 0 以上、差し込みは桁幅/2(正)、仕様ラベルは 45×45@455
            assert r['overhang'] >= 0.0
            assert r['embedment'] > 0.0
            assert r['label'] == '45×45@455'

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
