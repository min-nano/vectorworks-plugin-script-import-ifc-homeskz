"""解析フェーズ (ifc.floor_post) のテスト。

床束の配置間隔ロジック (``_post_offsets``) は単体で、命令組み立ては実 IFC
フィクスチャで検証する。いずれも vs 非依存。
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

    def test_post_count_matches_from_end_rule(self) -> None:
        # 床束の総数は各大引の平面芯線長に _post_offsets を適用した合計と一致する
        # (端部起点 910mm 間隔。910mm 以下の大引は 0 本)
        from vectorworks_plugin_import_ifc_homeskz.ifc.member import (
            _get_placement_3d,
            _get_profile_dims,
        )
        from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
            CLASS_OOBIKI,
            member_class_from_name,
        )

        ifc = _open(self.FILENAME)
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
            _ox, _oy, _oz, ax, ay, _az = placement
            _width, _height, length = dims
            span = math.hypot(ax * length, ay * length)
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
