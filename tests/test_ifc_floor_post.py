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
    def test_single_module_gets_one_centered_post(self) -> None:
        # 910mm 未満(単モジュールの大引=805mm)でも中央に 1 本入る
        offsets = floor_post._post_offsets(805.0)
        assert offsets == [402.5]

    def test_short_span_gets_one_post(self) -> None:
        # ちょうど 910mm 付近も区間 1 = 中央に 1 本
        assert floor_post._post_offsets(910.0) == [455.0]

    def test_two_module_span_gets_two_posts(self) -> None:
        # 2 モジュール(≈1820mm)は 2 区間 = 2 本、ピッチ 910mm
        offsets = floor_post._post_offsets(1820.0)
        assert offsets == [455.0, 1365.0]

    def test_posts_are_centered_and_within_span(self) -> None:
        # 4 区間(≈3640mm)は 4 本、いずれも [0, length] 内で 910mm ピッチ
        length = 3640.0
        offsets = floor_post._post_offsets(length)
        assert len(offsets) == 4
        assert all(0.0 < o < length for o in offsets)
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

    def test_every_ohbiki_gets_at_least_one_post(self) -> None:
        # 大引 1 本につき最低 1 本の床束が入る(単モジュールの大引も中央に 1 本)
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
        for element in list(ifc.by_type('IfcBeam')) + list(ifc.by_type('IfcMember')):
            if member_class_from_name(element.Name) != CLASS_OOBIKI:
                continue
            if _get_placement_3d(element) is None or _get_profile_dims(element) is None:
                continue
            ohbiki += 1

        posts = floor_post.build_floor_post_commands(ifc)
        assert ohbiki > 0
        assert len(posts) >= ohbiki

    def test_no_foundation_returns_empty(self) -> None:
        # 基礎が無いモデルでは配置先レイヤ(F-床束)が生成されないため空リスト
        class _NoFoundation:
            def by_type(self, _t: str) -> list[object]:
                return []

        assert floor_post.build_floor_post_commands(_NoFoundation()) == []  # type: ignore[arg-type]
