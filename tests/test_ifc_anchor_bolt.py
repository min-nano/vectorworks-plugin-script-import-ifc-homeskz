"""解析フェーズ (ifc.anchor_bolt) のテスト。

シンボル判定ロジックは単体で、命令組み立ては実 IFC フィクスチャで検証する。
いずれも vs 非依存。
"""
from __future__ import annotations

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import anchor_bolt

from tests.conftest import load_fixture_ifc


def _open(filename: str) -> ifcopenshell.file:
    return load_fixture_ifc(filename)


class TestResolveSymbol:
    def test_washered_bolt_is_m12(self) -> None:
        # 座金付き(Z1/Z2 等)は M12
        assert anchor_bolt.resolve_anchor_bolt_symbol(
            'アンカーボルト:Z1:定着長さ:360mm') == 'アンカーボルト_M12'
        assert anchor_bolt.resolve_anchor_bolt_symbol(
            'アンカーボルト:Z2:定着長さ:250mm') == 'アンカーボルト_M12'

    def test_washerless_bolt_is_m16(self) -> None:
        # 座金なしは M16
        assert anchor_bolt.resolve_anchor_bolt_symbol(
            'アンカーボルト:座金なし:定着長さ:360mm') == 'アンカーボルト_M16'


class TestIsAnchorBolt:
    def test_bolt_type_matches(self) -> None:
        assert anchor_bolt._is_anchor_bolt('アンカーボルト:Z1:定着長さ:360mm')

    def test_washer_type_does_not_match(self) -> None:
        # 座金(アンカーボルト座金:Zn)は対象外(接頭辞 "アンカーボルト:" に一致しない)
        assert not anchor_bolt._is_anchor_bolt('アンカーボルト座金:Z1')

    def test_none_does_not_match(self) -> None:
        assert not anchor_bolt._is_anchor_bolt(None)


class TestBuildFromFixture:
    FILENAME = '伏図次郎【2階】.ifc'

    def test_command_shape(self) -> None:
        ifc = _open(self.FILENAME)
        bolts = anchor_bolt.build_anchor_bolt_commands(ifc)
        assert bolts
        for bolt in bolts:
            assert bolt['layer'] == 'F-アンカーボルト'
            assert bolt['symbol'] in ('アンカーボルト_M12', 'アンカーボルト_M16')
            assert len(bolt['position']) == 2

    def test_counts_match_washered_and_washerless(self) -> None:
        ifc = _open(self.FILENAME)
        bolts = anchor_bolt.build_anchor_bolt_commands(ifc)
        # 伏図次郎: 84 本が座金付き(M12)、1 本が座金なし(M16)
        m12 = sum(1 for b in bolts if b['symbol'] == 'アンカーボルト_M12')
        m16 = sum(1 for b in bolts if b['symbol'] == 'アンカーボルト_M16')
        assert m12 == 84
        assert m16 == 1

    def test_positions_are_centered(self) -> None:
        ifc = _open(self.FILENAME)
        bolts = anchor_bolt.build_anchor_bolt_commands(ifc)
        # グリッド中心オフセット補正済みなら XY は 0 を中心にほぼ対称に分布する
        xs = [b['position'][0] for b in bolts]
        assert min(xs) < 0 < max(xs)
