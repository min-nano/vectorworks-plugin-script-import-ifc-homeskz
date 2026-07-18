"""ifc/noboribari.py (登り梁の位置補正) のテスト。vs 非依存。

登り梁の端部食い込み解消(受ける材・柱の面まで詰める)と、天端の屋根面(垂木下面)への
スナップ(勾配・高さを屋根勾配に合わせる)を検証する。中核ロジック(``_correct_one`` と
各ヘルパー)は命令データだけで動くため IFC 無しで検証し、IFC 連携(``_collect_roof_planes``・
``correct_noboribari``)はフィクスチャで検証する。
"""
from __future__ import annotations

import json
import math

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    ColumnCommand,
    MemberCommand,
    StoryBoundCommand,
)
from vectorworks_plugin_import_ifc_homeskz.ifc import build_document
from vectorworks_plugin_import_ifc_homeskz.ifc.noboribari import (
    _RoofPlane,
    _collect_roof_planes,
    _column_penetration,
    _correct_one,
    _end_trim,
    _roof_plane_for,
    correct_noboribari,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
    CLASS_NOBORIBARI,
    CLASS_MOYA,
)

from .conftest import load_fixture_ifc


def _bound(level: str, offset: float, story_offset: int = 0) -> StoryBoundCommand:
    return {'story_offset': story_offset, 'level': level, 'offset': offset}


def _nobori(
    start: list[float], end: list[float], elevation: float, end_elevation: float,
    width: float = 105.0, height: float = 105.0, level_z: float = 800.0,
) -> MemberCommand:
    """登り梁 member 命令を組み立てる(バインドは登り梁レベル、level_z=レベル絶対 Z)。"""
    return {
        'layer': '2-登り梁', 'member_id': 'nobori', 'class': CLASS_NOBORIBARI,
        'start': list(start), 'end': list(end), 'width': width, 'height': height,
        'elevation': elevation, 'end_elevation': end_elevation,
        'start_bound': _bound('登り梁', elevation - level_z),
        'end_bound': _bound('登り梁', end_elevation - level_z),
    }


def _member(
    start: list[float], end: list[float], elevation: float, width: float = 105.0,
    height: float = 150.0, member_class: str = CLASS_MOYA,
) -> MemberCommand:
    """受ける横架材(水平材)の member 命令を組み立てる。"""
    return {
        'layer': '2-母屋', 'member_id': 'recv', 'class': member_class,
        'start': list(start), 'end': list(end), 'width': width, 'height': height,
        'elevation': elevation, 'end_elevation': elevation,
        'start_bound': _bound('母屋', 0.0), 'end_bound': _bound('母屋', 0.0),
    }


def _column(pos: list[float], width: float, depth: float,
            elevation: float, cheight: float) -> ColumnCommand:
    return {
        'layer': '2to3-柱', 'member_id': 'col', 'class': '04構造-02木造',
        'position': list(pos), 'width': width, 'depth': depth,
        'elevation': elevation, 'height': cheight,
        'structural_use': '4', 'top_hardware': '', 'bottom_hardware': '',
        'bottom_bound': _bound('横架材天端', 0.0),
        'top_bound': _bound('横架材天端', 0.0, story_offset=1),
    }


def _flat_roof_plane(
    slope: float, z_at_origin: float, sign_x: float = 1.0,
) -> _RoofPlane:
    """+x 方向へ ``slope`` で下る/上る屋根面を作る(footprint は広い矩形)。

    z_at(wx, wy) = z_at_origin + slope * sign_x * wx になるよう法線を定める。
    ``sign_x``=+1 で +x へ行くほど高い(z 増)、-1 で低い。
    """
    # z = z0 + m*wx (m = slope*sign_x)。平面 z = az - (nx*(wx-ax))/nz(ny=0)。
    # -(nx)/nz = m → nx = -m*nz。単位化。
    m = slope * sign_x
    nz = 1.0 / math.hypot(m, 1.0)
    nx = -m * nz
    footprint = [(-10000.0, -10000.0), (10000.0, -10000.0),
                 (10000.0, 10000.0), (-10000.0, 10000.0)]
    return _RoofPlane((nx, 0.0, nz), (0.0, 0.0, 0.0), z_at_origin, footprint)


# ---------------------------------------------------------------------------
# _RoofPlane
# ---------------------------------------------------------------------------

class TestRoofPlane:
    def test_z_at_follows_slope(self) -> None:
        plane = _flat_roof_plane(0.25, 900.0)
        assert plane.z_at(0.0, 0.0) == pytest.approx(900.0)
        assert plane.z_at(1000.0, 0.0) == pytest.approx(1150.0)
        assert plane.z_at(-400.0, 0.0) == pytest.approx(800.0)

    def test_contains(self) -> None:
        plane = _flat_roof_plane(0.25, 900.0)
        assert plane.contains(0.0, 0.0)
        assert not plane.contains(20000.0, 0.0)


# ---------------------------------------------------------------------------
# _column_penetration
# ---------------------------------------------------------------------------

class TestColumnPenetration:
    def test_penetrating_end_returns_pullback(self) -> None:
        # 105mm 角柱、中心 (1050,0) → 手前の面(梁側=-x)は x=997.5。
        # 梁の終端 (1000,0) は外向き +x で入り、手前の面より 2.5mm 内側。
        # 内側 -x へ 2.5 戻すと面に出る。
        col = _column([1050.0, 0.0], 105.0, 105.0, 0.0, 2000.0)
        assert _column_penetration(1000.0, 0.0, 1.0, 0.0, col) == pytest.approx(2.5)

    def test_outside_returns_zero(self) -> None:
        # 端点 x=900 は柱 [997.5..1102.5] の外 → 食い込み 0。
        col = _column([1050.0, 0.0], 105.0, 105.0, 0.0, 2000.0)
        assert _column_penetration(900.0, 0.0, 1.0, 0.0, col) == 0.0

    def test_penetration_exits_via_y_face(self) -> None:
        # y 方向に入る端点。中心 (0,1050)・外向き +y → 手前面 y=997.5 まで 2.5mm。
        col = _column([0.0, 1050.0], 105.0, 105.0, 0.0, 2000.0)
        assert _column_penetration(0.0, 1000.0, 0.0, 1.0, col) == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# _end_trim
# ---------------------------------------------------------------------------

class TestEndTrim:
    def test_trims_to_member_face(self) -> None:
        # 受ける母屋: y 方向に走る中心 x=1050・半幅 52.5 → 手前の面 x=997.5。
        # 登り梁の終端 (1000,0)・外向き +x は面より 2.5mm 内側 → 2.5mm 詰める。
        recv = _member([1050.0, -1000.0], [1050.0, 1000.0], 1000.0, width=105.0)
        s = _end_trim(1000.0, 0.0, 1.0, 0.0, 900.0, 1050.0, [recv], [])
        assert s == pytest.approx(2.5)

    def test_z_gated(self) -> None:
        # Z 範囲が離れた受け材は対象外(食い込み 0)。
        recv = _member([1050.0, -1000.0], [1050.0, 1000.0], 5000.0, width=105.0)
        s = _end_trim(1000.0, 0.0, 1.0, 0.0, 900.0, 1050.0, [recv], [])
        assert s == 0.0

    def test_trims_to_column_face(self) -> None:
        # 柱(中心 1050・半幅 52.5)に食い込む端点 (1000,0)・外向き +x → 2.5mm 詰める。
        col = _column([1050.0, 0.0], 105.0, 105.0, 900.0, 300.0)
        s = _end_trim(1000.0, 0.0, 1.0, 0.0, 950.0, 1050.0, [], [col])
        assert s == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# _roof_plane_for
# ---------------------------------------------------------------------------

class TestRoofPlaneFor:
    def test_selects_aligned_plane(self) -> None:
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1300.0)
        aligned = _flat_roof_plane(0.25, 900.0)          # +x 勾配(梁と平行)
        crossing = _RoofPlane((0.0, -0.2425, 0.9701), (0.0, 0.0, 0.0), 900.0,
                              [(-10000.0, -10000.0), (10000.0, -10000.0),
                               (10000.0, 10000.0), (-10000.0, 10000.0)])
        big = [(-10000.0, -10000.0), (10000.0, -10000.0),
               (10000.0, 10000.0), (-10000.0, 10000.0)]
        flat = _RoofPlane((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 900.0, big)  # 水平面は除外
        assert _roof_plane_for(cmd, [flat, crossing, aligned], 0.0, 0.0) is aligned

    def test_none_when_no_aligned_plane(self) -> None:
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1300.0)
        crossing = _RoofPlane((0.0, -0.2425, 0.9701), (0.0, 0.0, 0.0), 900.0,
                              [(-10000.0, -10000.0), (10000.0, -10000.0),
                               (10000.0, 10000.0), (-10000.0, 10000.0)])
        assert _roof_plane_for(cmd, [crossing], 0.0, 0.0) is None

    def test_none_for_degenerate_length(self) -> None:
        # 平面投影長が極小の登り梁は屋根面を求めない。
        cmd = _nobori([0.0, 0.0], [0.0, 0.0], 1000.0, 1000.0)
        assert _roof_plane_for(cmd, [_flat_roof_plane(0.25, 900.0)], 0.0, 0.0) is None


# ---------------------------------------------------------------------------
# _correct_one (中核: 端部詰め + 屋根スナップ)
# ---------------------------------------------------------------------------

class TestCorrectOne:
    def test_snaps_pitch_and_height_to_roof(self) -> None:
        """急な登り梁の天端を屋根面へスナップし勾配・高さを一致させる。"""
        # 梁 pitch 0.3(1000→1300)、屋根 pitch 0.25。level_z=800。
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1300.0, level_z=800.0)
        plane = _flat_roof_plane(0.25, 900.0)
        out = _correct_one(cmd, [plane], [], [], 0.0, 0.0)
        assert out['elevation'] == pytest.approx(900.0)
        assert out['end_elevation'] == pytest.approx(1150.0)
        d = math.hypot(out['end'][0] - out['start'][0], out['end'][1] - out['start'][1])
        assert (out['end_elevation'] - out['elevation']) / d == pytest.approx(0.25)
        # バインド offset は新しい天端 − レベル絶対 Z(800)
        assert out['start_bound']['offset'] == pytest.approx(100.0)
        assert out['end_bound']['offset'] == pytest.approx(350.0)
        assert out['start_bound']['level'] == '登り梁'

    def test_trims_penetrating_ends(self) -> None:
        """端部が受ける材に食い込む登り梁を面まで詰める。"""
        # 梁 (0,0)->(1000,0)。終端側に x=1000 中心・半幅 52.5 の母屋(y 走り)。
        # 端点 x=1000 は母屋中心にあり 52.5 食い込む。詰めて端点 x=947.5 に。
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1150.0, level_z=800.0)
        recv = _member([1000.0, -1000.0], [1000.0, 1000.0], 1120.0, width=105.0)
        out = _correct_one(cmd, [], [recv], [], 0.0, 0.0)
        assert out['end'][0] == pytest.approx(947.5)
        assert out['start'][0] == pytest.approx(0.0)  # 始端は受け材が無く不変

    def test_no_roof_keeps_height_but_trims(self) -> None:
        """屋根面が無い登り梁は天端をそのまま残し、端部の食い込みだけ詰める。"""
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1300.0, level_z=800.0)
        recv = _member([1000.0, -1000.0], [1000.0, 1000.0], 1250.0, width=105.0)
        out = _correct_one(cmd, [], [recv], [], 0.0, 0.0)
        assert out['elevation'] == pytest.approx(1000.0)      # 天端そのまま
        assert out['end_elevation'] == pytest.approx(1300.0)
        assert out['end'][0] == pytest.approx(947.5)          # 食い込みは詰める

    def test_degenerate_length_returned_unchanged(self) -> None:
        """平面投影長が極小の登り梁はそのまま返す。"""
        cmd = _nobori([5.0, 5.0], [5.0, 5.0], 1000.0, 1000.0)
        assert _correct_one(cmd, [], [], [], 0.0, 0.0) is cmd

    def test_over_trim_is_skipped(self) -> None:
        """両端を詰めると極小長になる場合は詰めない(端点そのまま)。"""
        cmd = _nobori([0.0, 0.0], [4.0, 0.0], 1000.0, 1000.6)
        # 両端の直近に受け材を置き、各端 2.5mm 詰めると全長 4→-1 になる → 詰めない。
        r1 = _member([-50.0, -1000.0], [-50.0, 1000.0], 1000.0, width=105.0)
        r2 = _member([54.0, -1000.0], [54.0, 1000.0], 1000.0, width=105.0)
        out = _correct_one(cmd, [], [r1, r2], [], 0.0, 0.0)
        assert out['start'] == [pytest.approx(0.0), pytest.approx(0.0)]
        assert out['end'] == [pytest.approx(4.0), pytest.approx(0.0)]

    def test_z_gated_column_not_trimmed(self) -> None:
        """Z 範囲が離れた柱は端部詰めの対象にしない。"""
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1150.0)
        col = _column([1050.0, 0.0], 105.0, 105.0, 5000.0, 300.0)  # 遠い Z
        out = _correct_one(cmd, [], [], [col], 0.0, 0.0)
        assert out['end'][0] == pytest.approx(1000.0)

    def test_degenerate_receiver_ignored(self) -> None:
        """平面投影長が極小の受け材は無視する。"""
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1150.0)
        recv = _member([1000.0, 0.0], [1000.0, 0.0], 1120.0, width=105.0)  # len 0
        out = _correct_one(cmd, [], [recv], [], 0.0, 0.0)
        assert out['end'][0] == pytest.approx(1000.0)

    def test_tiny_penetration_not_trimmed(self) -> None:
        """極小の食い込み(_MIN_TRIM 未満)は詰めない。"""
        cmd = _nobori([0.0, 0.0], [1000.0, 0.0], 1000.0, 1150.0, level_z=800.0)
        # 端点 x=1000、母屋中心 x=1000.4・半幅 52.5 → 食い込み 52.9 だが…
        # 端点 x=1000 は面 (1000.4-52.5=947.9) より内側で食い込み大。極小ケースは
        # 面が端点にほぼ一致する配置で作る: 中心 x=1052.4、半幅 52.5 → 面 999.9、
        # 端点 1000 は 0.1mm だけ内側 → _MIN_TRIM(0.5) 未満で詰めない。
        recv = _member([1052.4, -1000.0], [1052.4, 1000.0], 1120.0, width=105.0)
        out = _correct_one(cmd, [], [recv], [], 0.0, 0.0)
        assert out['end'][0] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# correct_noboribari / _collect_roof_planes (IFC 連携)
# ---------------------------------------------------------------------------

class TestCorrectNoboribariIntegration:
    def test_passes_non_noboribari_through_unchanged(self) -> None:
        """登り梁でない材は素通し(件数・並び順・内容を保つ)。"""
        ifc = load_fixture_ifc('サンプル1 (住木邸新築工事).ifc')
        from vectorworks_plugin_import_ifc_homeskz.ifc.member import build_member_commands
        from vectorworks_plugin_import_ifc_homeskz.ifc.column import build_column_commands
        members = build_member_commands(ifc)
        columns = build_column_commands(ifc, members)
        assert not any(m['class'] == CLASS_NOBORIBARI for m in members)
        out = correct_noboribari(ifc, members, columns)
        assert out == members

    def test_collects_roof_planes_from_fixture(self) -> None:
        """屋根版を持つフィクスチャから屋根面を集める。"""
        ifc = load_fixture_ifc('サンプル1 (住木邸新築工事).ifc')
        planes = _collect_roof_planes(ifc)
        # サンプル1 は屋根版を持つ(垂木・野地板が導出される)
        assert len(planes) > 0
        for p in planes:
            assert math.hypot(p.normal[0], p.normal[1]) > 0.0  # 勾配方向が定まる

    def test_result_is_json_serializable(self) -> None:
        ifc = load_fixture_ifc('サンプル1 (住木邸新築工事).ifc')
        doc = build_document(ifc)
        assert json.loads(json.dumps(doc['members'])) == doc['members']

    def test_processes_injected_noboribari(self) -> None:
        """members に含めた登り梁は補正(端部詰め)される(素通ししない)。"""
        ifc = load_fixture_ifc('サンプル1 (住木邸新築工事).ifc')
        # フィクスチャの屋根版と重ならない位置に合成登り梁 + 受け材を置く
        # (屋根スナップは効かないが、端部の食い込み詰めが働くことを検証する)。
        nobori = _nobori([50000.0, 0.0], [51000.0, 0.0], 1000.0, 1150.0)
        recv = _member([51050.0, -1000.0], [51050.0, 1000.0], 1120.0, width=105.0)
        recv['layer'] = '2-登り梁'  # Z 重なりのみで判定するためレイヤは不問
        out = correct_noboribari(ifc, [nobori, recv], [])
        # 登り梁の終端が受け材の手前の面 (51050 - 52.5 = 50997.5) まで詰められる
        assert out[0]['end'][0] == pytest.approx(50997.5)
        # 受け材(登り梁でない)は不変
        assert out[1] == recv
