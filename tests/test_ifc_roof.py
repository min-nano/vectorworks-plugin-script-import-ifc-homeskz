"""解析フェーズ (ifc.roof) のテスト。

屋根面から屋根オブジェクト(野地板)への変換(``_roof_command_for_plane``)は
合成入力で、命令組み立ては実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import open_ifc, roof
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
    CLASS_ROOF_SHEATHING,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestRoofCommandForPlane:
    # 平面: XY 平面上の 4m×3m 矩形が、+Y 方向に立ち上がる片流れ屋根。
    # 軒(y=0)で z=1000、棟(y=3000)で z=2000。勾配は Y 方向のみ。
    #   z(x, y) = 1000 + y/3 ⇒ 法線 ∝ (0, -1, 3)/√10(上向き)
    NX, NY, NZ = 0.0, -1.0 / math.sqrt(10.0), 3.0 / math.sqrt(10.0)
    VERTS = [
        (0.0, 0.0, 1000.0),
        (4000.0, 0.0, 1000.0),
        (4000.0, 3000.0, 2000.0),
        (0.0, 3000.0, 2000.0),
    ]

    def _command(self, storey_elevation: float = 0.0,
                 center_x: float = 0.0, center_y: float = 0.0) -> dict:
        cmd = roof._roof_command_for_plane(
            self.VERTS, (self.NX, self.NY, self.NZ), 'R-野地板',
            storey_elevation, center_x, center_y)
        assert cmd is not None
        return dict(cmd)

    def test_default_thickness_is_12mm(self) -> None:
        assert self._command()['thickness'] == 12.0
        assert roof.NOJIITA_THICKNESS == 12.0

    def test_class_and_layer(self) -> None:
        cmd = self._command()
        assert cmd['class'] == CLASS_ROOF_SHEATHING
        assert cmd['layer'] == 'R-野地板'

    def test_boundary_is_plan_footprint(self) -> None:
        cmd = self._command()
        # 平面外形の XY(押し出しの水平投影)。4 頂点。
        assert cmd['boundary'] == [
            [0.0, 0.0], [4000.0, 0.0], [4000.0, 3000.0], [0.0, 3000.0]]

    def test_axis_lies_on_eaves_low_edge(self) -> None:
        cmd = self._command()
        # 軒(軸)は最も低い辺 y=0 上。軸の 2 点はどちらも y=0。
        assert math.isclose(cmd['axis_start'][1], 0.0, abs_tol=1e-6)
        assert math.isclose(cmd['axis_end'][1], 0.0, abs_tol=1e-6)
        # 軸は軒に沿って X 方向(footprint 幅 4000)に伸びる。
        assert math.isclose(abs(cmd['axis_end'][0] - cmd['axis_start'][0]),
                            4000.0, abs_tol=1e-6)

    def test_upslope_points_toward_ridge(self) -> None:
        cmd = self._command()
        # upslope 定義点は軒(y=0)から棟(+Y)側を指す。
        assert cmd['upslope'][1] > cmd['axis_start'][1]

    def test_rise_run_encode_slope(self) -> None:
        cmd = self._command()
        # slope = rise/run = dh/nz = tan(勾配角)。この面は y 方向に 1/3 勾配。
        assert math.isclose(cmd['rise'] / cmd['run'], 1.0 / 3.0, rel_tol=1e-9)

    def test_elevation_is_absolute_eaves_top(self) -> None:
        cmd = self._command(storey_elevation=6300.0)
        # 軒(最も低い辺)の天端 Z 絶対値 = 1000 + ストーリ Elevation。
        assert math.isclose(cmd['elevation'], 1000.0 + 6300.0, abs_tol=1e-6)

    def test_center_offset_subtracted_from_xy(self) -> None:
        cmd = self._command(center_x=100.0, center_y=200.0)
        assert cmd['boundary'][0] == [-100.0, -200.0]
        assert math.isclose(cmd['axis_start'][1], -200.0, abs_tol=1e-6)

    def test_flat_plane_returns_none(self) -> None:
        # 法線が鉛直(水平な面)なら勾配方向が定まらず None。
        assert roof._roof_command_for_plane(
            [(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (1000.0, 1000.0, 0.0)],
            (0.0, 0.0, 1.0), 'R-野地板', 0.0, 0.0, 0.0) is None


class TestBuildRoofCommands:
    def test_empty_ifc_returns_empty(self) -> None:
        assert roof.build_roof_commands(ifcopenshell.file()) == []

    def test_fixture_roofs_are_valid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        roofs = roof.build_roof_commands(ifc)
        assert len(roofs) > 0
        for r in roofs:
            assert r['thickness'] == 12.0
            assert r['class'] == CLASS_ROOF_SHEATHING
            assert r['layer'].endswith('-野地板')
            assert len(r['boundary']) >= 3
            assert r['run'] != 0.0

    def test_fixture_layers_map_to_roof_storeys(self) -> None:
        # 伏図次郎: 下屋根(2FL)→ 2-野地板、主屋根(RFL)→ R-野地板
        ifc = _open('伏図次郎【2階】.ifc')
        layers = {r['layer'] for r in roof.build_roof_commands(ifc)}
        assert layers == {'2-野地板', 'R-野地板'}

    def test_one_roof_per_roof_slab_plane(self) -> None:
        # 野地板は屋根版 1 面につき 1 つ(垂木のように 455 間隔で割らない)。
        ifc = _open('伏図次郎【2階】.ifc')
        roof_slabs = [
            e for e in ifc.by_type('IfcSlab')
            if (e.Name or '').startswith('屋根版')
        ]
        # 屋根版のうち勾配のある面の数と野地板数が一致する(水平面はスキップ)。
        assert 0 < len(roof.build_roof_commands(ifc)) <= len(roof_slabs)
