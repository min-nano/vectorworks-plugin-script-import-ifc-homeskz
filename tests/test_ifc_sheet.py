"""解析フェーズ (ifc.sheet) のテスト。

基礎の有無に応じた基礎伏図シートと、各階の柱梁伏図シートの命令が組み立てられる
ことを、空の IFC と実 IFC フィクスチャで検証する。vs 非依存。
"""
from __future__ import annotations

import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import open_ifc, sheet

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestBuildFoundationSheetCommands:
    def test_no_sheet_without_foundation(self) -> None:
        # 基礎要素が無ければ基礎伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_foundation_sheet_commands(empty) == []

    def test_foundation_plan_sheet_from_fixture(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_foundation_sheet_commands(ifc)
        assert len(sheets) == 1
        command = sheets[0]
        assert command['number'] == '1'
        assert command['title'] == '基礎伏図'

    def test_viewport_shows_foundation_and_grid_layers(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        viewport = sheet.build_foundation_sheet_commands(ifc)[0]['viewport']
        assert viewport['drawing_title'] == '基礎伏図'
        assert viewport['drawing_number'] == '1'
        # 底盤・立上り・アンカーボルト・通り芯の順で表示する
        assert viewport['layers'] == [
            'F-底盤', 'F-立上り', 'F-アンカーボルト', '共通']


class TestBuildFloorFramingSheetCommands:
    def test_no_sheet_without_stories(self) -> None:
        # ストーリが無ければ柱梁伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_floor_framing_sheet_commands(empty) == []

    def test_one_sheet_per_story(self) -> None:
        # フィクスチャは 2 階建て(1階・2階・屋根)なので 3 枚
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_floor_framing_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '1階床伏図', '2階床伏図', '小屋伏図']
        # シートレイヤ番号は基礎伏図(1)に続けて 2 から
        assert [s['number'] for s in sheets] == ['2', '3', '4']

    def test_first_floor_shows_beam_column_anchor_slab_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        first = sheet.build_floor_framing_sheet_commands(ifc)[0]
        assert first['title'] == '1階床伏図'
        assert first['viewport']['drawing_title'] == '1階床伏図'
        assert first['viewport']['drawing_number'] == '2'
        # 横架材・柱・アンカーボルト・床・通り芯の順
        assert first['viewport']['layers'] == [
            '1-横架材天端', '1-柱', 'F-アンカーボルト', '1-FL', '共通']

    def test_middle_floor_shows_beam_column_slab_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        middle = sheet.build_floor_framing_sheet_commands(ifc)[1]
        assert middle['title'] == '2階床伏図'
        # 中間階はアンカーボルトを含まない(横架材・柱・下階柱・床・通り芯)
        assert middle['viewport']['layers'] == [
            '2-横架材天端', '2-柱', '2-下階柱', '2-FL', '共通']

    def test_roof_shows_beam_column_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        roof = sheet.build_floor_framing_sheet_commands(ifc)[-1]
        assert roof['title'] == '小屋伏図'
        # 最上階は軒高の横架材・柱(束)・下階柱・通り芯のみ(床は無い)
        assert roof['viewport']['layers'] == ['R-軒高', 'R-柱', 'R-下階柱', '共通']


class TestBuildSheetCommands:
    def test_foundation_then_floor_framing(self) -> None:
        # 基礎伏図に続けて各階の柱梁伏図が並ぶ
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '基礎伏図', '1階床伏図', '2階床伏図', '小屋伏図']
        assert [s['number'] for s in sheets] == ['1', '2', '3', '4']
