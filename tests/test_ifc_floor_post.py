"""解析フェーズ (ifc.floor_post) のテスト。

床束の配置間隔ロジック (``_post_offsets``) と土台芯の探索 (``_shin_reference``)
は単体で、命令組み立ては実 IFC フィクスチャで検証する。いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import floor_post, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


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

    def test_posts_measured_from_support_shin(self) -> None:
        # 床束の総数は各大引の「支持材芯どうしの区間」に _post_offsets を適用した
        # 合計と一致する(端部=実部材端ではなく支持材芯。910mm 以下の区間は 0 本)。
        from vectorworks_plugin_import_ifc_homeskz.ifc.member import (
            _get_placement_3d,
            _get_profile_dims,
        )
        from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
            CLASS_OOBIKI,
            member_class_from_name,
        )

        ifc = _open(self.FILENAME)
        supports = floor_post._collect_support_lines(ifc)
        ohbiki = 0
        expected = 0
        for element in list(ifc.by_type('IfcBeam')) + list(ifc.by_type('IfcMember')):
            if member_class_from_name(element.Name) != CLASS_OOBIKI:
                continue
            placement = _get_placement_3d(element)
            dims = _get_profile_dims(element)
            if placement is None or dims is None:
                continue
            ohbiki += 1
            ox, oy, _oz, ax, ay, _az = placement
            _width, _height, length = dims
            ex, ey = ox + ax * length, oy + ay * length
            seg = math.hypot(ex - ox, ey - oy)
            if seg <= 0.0:
                continue
            ux, uy = (ex - ox) / seg, (ey - oy) / seg
            start = floor_post._shin_reference(ox, oy, ux, uy, supports) or (ox, oy)
            end = floor_post._shin_reference(ex, ey, ux, uy, supports) or (ex, ey)
            span = (end[0] - start[0]) * ux + (end[1] - start[1]) * uy
            expected += len(floor_post._post_offsets(span))

        posts = floor_post.build_floor_post_commands(ifc)
        assert ohbiki > 0
        assert expected > 0
        assert len(posts) == expected

    def test_no_foundation_returns_empty(self) -> None:
        # 基礎が無いモデルでは配置先レイヤ(F-床束)が生成されないため空リスト
        class _NoFoundation:
            def by_type(self, _t: str) -> list[object]:
                return []

        assert floor_post.build_floor_post_commands(_NoFoundation()) == []  # type: ignore[arg-type]
