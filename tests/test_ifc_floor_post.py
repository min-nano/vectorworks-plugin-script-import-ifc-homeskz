"""解析フェーズ (ifc.floor_post) のテスト。

床束の配置間隔ロジック (``_post_offsets``) と土台芯の探索 (``_shin_reference``)
は単体で、命令組み立ては実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import floor_post

from tests.conftest import load_fixture_ifc


def _open(filename: str) -> ifcopenshell.file:
    return load_fixture_ifc(filename)


class TestPostOffsets:
    def test_single_module_gets_no_post(self) -> None:
        # 910mm 以下(単モジュールの大引=805mm)は床束 0 本(両端が受ける)
        assert floor_post._post_offsets(805.0) == []

    def test_exactly_interval_gets_no_post(self) -> None:
        # ちょうど 910mm は終点に来るため床束 0 本(端点には置かない)
        assert floor_post._post_offsets(910.0) == []

    def test_one_post_from_end(self) -> None:
        # 910mm を超え 1820mm 以下は 910mm の位置に 1 本、残りは半端
        assert floor_post._post_offsets(1715.0) == [910.0]
        assert floor_post._post_offsets(1820.0) == [910.0]

    def test_posts_at_fixed_interval_from_start(self) -> None:
        # 始点から 910mm ずつ並び、終点(反対側)は 910mm 未満の半端でよい
        offsets = floor_post._post_offsets(2625.0)
        assert offsets == [910.0, 1820.0]
        # 最後の床束と終点の間隔(半端)は 910mm 未満
        assert 0.0 < 2625.0 - offsets[-1] < 910.0

    def test_posts_keep_910_pitch(self) -> None:
        # 長い大引でもピッチはちょうど 910mm(等分ではなく端部起点)
        offsets = floor_post._post_offsets(3640.0)
        assert offsets == [910.0, 1820.0, 2730.0]
        diffs = [b - a for a, b in zip(offsets, offsets[1:])]
        assert all(abs(d - 910.0) < 1e-6 for d in diffs)

    def test_zero_length_returns_empty(self) -> None:
        assert floor_post._post_offsets(0.0) == []


class TestShinReference:
    # 幅 105mm の支持材(土台または他の大引)を x=0 の位置に Y 方向へ通す
    # (芯線 x=0、区間 y∈[-1000,1000])。
    SUPPORT: list[floor_post._SupportLine] = [(0.0, -1000.0, 0.0, 1.0, 2000.0, 105.0)]

    def test_end_inset_from_support_returns_shin(self) -> None:
        # 大引端が支持材芯より半支持材厚(52.5mm)内側にある(x=52.5)→ 支持材芯 x=0 を返す
        ref = floor_post._shin_reference(52.5, 300.0, 1.0, 0.0, self.SUPPORT)
        assert ref is not None
        assert abs(ref[0] - 0.0) < 1e-6
        assert abs(ref[1] - 300.0) < 1e-6

    def test_end_flush_with_shin_returns_same_point(self) -> None:
        # 端が支持材芯ちょうど(x=0)なら同じ点を返す
        ref = floor_post._shin_reference(0.0, 100.0, 1.0, 0.0, self.SUPPORT)
        assert ref is not None
        assert abs(ref[0]) < 1e-6

    def test_end_far_from_support_returns_none(self) -> None:
        # 端が支持材の footprint(半支持材厚)より遠い(x=200)→ 受けていない
        assert floor_post._shin_reference(200.0, 300.0, 1.0, 0.0, self.SUPPORT) is None

    def test_parallel_support_returns_none(self) -> None:
        # 大引と平行な支持材(自身の芯線・同一直線上の大引を含む)は交点が定まらない
        assert floor_post._shin_reference(52.5, 300.0, 0.0, 1.0, self.SUPPORT) is None

    def test_outside_support_segment_returns_none(self) -> None:
        # 交点が支持材の区間外(y=5000 は区間 [-1000,1000] の外)→ 受けていない
        assert floor_post._shin_reference(52.5, 5000.0, 1.0, 0.0, self.SUPPORT) is None


class TestMergeCollinear:
    def test_gap_none_when_not_parallel(self) -> None:
        # 直交する大引はすき間なし(None)
        a = (0.0, 0.0, 1000.0, 0.0)
        b = (500.0, 0.0, 500.0, 1000.0)
        assert floor_post._collinear_gap(a, b) is None

    def test_gap_none_when_offset_line(self) -> None:
        # 平行だが別の直線上(直交距離あり)はすき間なし(None)
        a = (0.0, 0.0, 1000.0, 0.0)
        b = (1200.0, 50.0, 2000.0, 50.0)
        assert floor_post._collinear_gap(a, b) is None

    def test_gap_between_collinear_segments(self) -> None:
        # 同一直線上・105mm すき間(継手)
        a = (0.0, 0.0, 1000.0, 0.0)
        b = (1105.0, 0.0, 2000.0, 0.0)
        gap = floor_post._collinear_gap(a, b)
        assert gap is not None
        assert abs(gap - 105.0) < 1e-6

    def test_gap_zero_when_touching(self) -> None:
        a = (0.0, 0.0, 1000.0, 0.0)
        b = (1000.0, 0.0, 2000.0, 0.0)
        assert floor_post._collinear_gap(a, b) == 0.0

    def test_joint_merged_into_one_run(self) -> None:
        # 継手(105mm すき間)で分断された 3 本は 1 連(0〜4105)に統合される
        lines = [
            (0.0, 0.0, 1000.0, 0.0),
            (1105.0, 0.0, 2000.0, 0.0),
            (2105.0, 0.0, 4105.0, 0.0),
        ]
        runs = floor_post._merge_collinear_ohbiki(lines)
        assert len(runs) == 1
        sx, sy, ex, ey = runs[0]
        assert abs(sx - 0.0) < 1e-6 and abs(ex - 4105.0) < 1e-6
        assert abs(sy) < 1e-6 and abs(ey) < 1e-6

    def test_distant_collinear_not_merged(self) -> None:
        # 同一直線上でも 1 モジュール以上離れた大引は別材(統合しない)
        lines = [
            (0.0, 0.0, 1000.0, 0.0),
            (2000.0, 0.0, 3000.0, 0.0),   # すき間 1000mm > 半モジュール
        ]
        runs = floor_post._merge_collinear_ohbiki(lines)
        assert len(runs) == 2

    def test_perpendicular_not_merged(self) -> None:
        lines = [
            (0.0, 0.0, 1000.0, 0.0),
            (500.0, 0.0, 500.0, 1000.0),
        ]
        runs = floor_post._merge_collinear_ohbiki(lines)
        assert len(runs) == 2


class TestBuildFromFixture:
    FILENAME = '伏図次郎【2階】.ifc'

    def test_command_shape(self) -> None:
        ifc = _open(self.FILENAME)
        posts = floor_post.build_floor_post_commands(ifc)
        assert posts
        for post in posts:
            assert post['layer'] == 'F-床束'
            assert post['symbol'] == '床束'
            assert len(post['position']) == 2
            assert all(isinstance(c, float) for c in post['position'])

    def test_support_lines_include_ohbiki(self) -> None:
        # 支持材芯には土台だけでなく大引も含める(二次大引の端を大引芯基準にするため)
        from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
            CLASS_DODAI,
            CLASS_OOBIKI,
            member_class_from_name,
        )

        ifc = _open(self.FILENAME)
        supports = floor_post._collect_support_lines(ifc)
        dodai = ohbiki = 0
        for element in list(ifc.by_type('IfcBeam')) + list(ifc.by_type('IfcMember')):
            cls = member_class_from_name(element.Name)
            if cls == CLASS_DODAI:
                dodai += 1
            elif cls == CLASS_OOBIKI:
                ohbiki += 1
        assert dodai > 0 and ohbiki > 0
        # 大引を含めるため、支持材数は土台のみより多い
        assert len(supports) > dodai

    def test_collinear_ohbiki_are_merged(self) -> None:
        # 継手で分断された大引が統合され、連の数は元の大引本数より少なくなる
        ifc = _open(self.FILENAME)
        lines = floor_post._collect_ohbiki_lines(ifc)
        runs = floor_post._merge_collinear_ohbiki(lines)
        assert len(lines) > 0
        assert len(runs) < len(lines)

    def test_posts_measured_from_merged_run_shin(self) -> None:
        # 床束の総数は「継手統合後の大引 1 連の支持材芯どうしの区間」に _post_offsets を
        # 適用した合計と一致する(継手は端部として扱わず、支持材芯を端部にする)。
        ifc = _open(self.FILENAME)
        supports = floor_post._collect_support_lines(ifc)
        runs = floor_post._merge_collinear_ohbiki(floor_post._collect_ohbiki_lines(ifc))
        expected = 0
        for sx, sy, ex, ey in runs:
            seg = math.hypot(ex - sx, ey - sy)
            if seg <= 0.0:
                continue
            ux, uy = (ex - sx) / seg, (ey - sy) / seg
            start = floor_post._shin_reference(sx, sy, ux, uy, supports) or (sx, sy)
            end = floor_post._shin_reference(ex, ey, ux, uy, supports) or (ex, ey)
            span = (end[0] - start[0]) * ux + (end[1] - start[1]) * uy
            expected += len(floor_post._post_offsets(span))

        posts = floor_post.build_floor_post_commands(ifc)
        assert len(runs) > 0
        assert expected > 0
        assert len(posts) == expected

    def test_no_foundation_returns_empty(self) -> None:
        # 基礎が無いモデルでは配置先レイヤ(F-床束)が生成されないため空リスト
        class _NoFoundation:
            def by_type(self, _t: str) -> list[object]:
                return []

        assert floor_post.build_floor_post_commands(_NoFoundation()) == []  # type: ignore[arg-type]
