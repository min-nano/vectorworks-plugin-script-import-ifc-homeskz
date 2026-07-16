"""解析フェーズ (ifc.floor) のテスト。

床板 (IfcSlab "床版") の抽出・FL レイヤ振り分け・高さ(床下端=横架材天端)を
実 IFC フィクスチャで検証する。vs 非依存。
"""
from __future__ import annotations

import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import build_floor_commands, open_ifc
from vectorworks_plugin_import_ifc_homeskz.ifc.floor import (
    FLOOR_THICKNESS,
    build_floor_commands as build_floor_commands_direct,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.story import resolve_beam_top_offset
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import CLASS_FLOOR

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestBuildFloorCommands:
    def test_sample1_has_floor_on_each_non_top_fl_layer(self) -> None:
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        commands = build_floor_commands(ifc)
        # 床版は 1FL・2FL に 1 枚ずつ(RFL=屋根には床板は無い)
        assert len(commands) == 2
        layers = sorted(c['layer'] for c in commands)
        assert layers == ['1-FL', '2-FL']

    def test_thickness_fixed_at_24(self) -> None:
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        commands = build_floor_commands(ifc)
        assert commands
        # 厚みは IFC の押し出し厚(28mm 等)ではなく要件どおり 24mm 固定
        assert all(c['thickness'] == FLOOR_THICKNESS == 24.0 for c in commands)

    def test_class_is_floor_board(self) -> None:
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        commands = build_floor_commands(ifc)
        assert all(c['class'] == CLASS_FLOOR for c in commands)

    def test_bottom_elevation_equals_beam_top(self) -> None:
        """床下端(elevation)が配置階の横架材天端(絶対 Z)に一致する。"""
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        storeys = sorted(
            [s for s in ifc.by_type('IfcBuildingStorey')
             if (s.Name or '').upper().endswith('FL')],
            key=lambda s: float(s.Elevation or 0.0),
        )
        # 1FL・2FL の横架材天端(絶対 Z)
        beam_top_by_layer = {}
        for i, s in enumerate(storeys[:-1]):  # 最上階を除く
            layer = f'{i + 1}-FL'
            beam_top_by_layer[layer] = float(s.Elevation or 0.0) + \
                resolve_beam_top_offset(s)

        for c in build_floor_commands(ifc):
            assert c['elevation'] == beam_top_by_layer[c['layer']]

    def test_bound_to_beam_top_level_offset_zero(self) -> None:
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        for c in build_floor_commands(ifc):
            bound = c['bound']
            assert bound['story_offset'] == 0
            assert bound['level'] == '横架材天端'
            assert bound['offset'] == 0.0

    def test_boundary_is_centered_polygon(self) -> None:
        """外形はグリッド中心オフセット済みの 3 点以上のポリゴン。"""
        ifc = _open('サンプル1 (住木邸新築工事).ifc')
        for c in build_floor_commands(ifc):
            assert len(c['boundary']) >= 3
            for pt in c['boundary']:
                assert len(pt) == 2
        # センタリングにより原点近傍に頂点が分布する(生の IFC 座標は数万 mm)。
        max_abs = max(abs(v) for c in build_floor_commands(ifc)
                      for pt in c['boundary'] for v in pt)
        assert max_abs < 30000.0

    def test_floors_only_on_existing_fl_layers(self) -> None:
        """振り分け先は必ず非最上階の FL レイヤ(屋根に床板を置かない)。"""
        for filename in ['サンプル1 (住木邸新築工事).ifc',
                         'スキップフロア_サンプル.ifc',
                         'グレー本モデルプラン1【3階】.ifc']:
            ifc = _open(filename)
            storeys = [s for s in ifc.by_type('IfcBuildingStorey')
                       if (s.Name or '').upper().endswith('FL')]
            n = len(storeys)
            valid_layers = {f'{i + 1}-FL' for i in range(n - 1)}
            for c in build_floor_commands(ifc):
                assert c['layer'] in valid_layers

    def test_public_export_matches_module(self) -> None:
        # ifc パッケージの公開名と直接 import が同じ関数を指すこと
        assert build_floor_commands is build_floor_commands_direct
