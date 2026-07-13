"""解析フェーズ (ifc.sheet) のテスト。

基礎の有無に応じて基礎伏図シートの命令が組み立てられることを、空の IFC と
実 IFC フィクスチャで検証する。vs 非依存。
"""
from __future__ import annotations

import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc import open_ifc, sheet

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


class TestBuildSheetCommands:
    def test_no_sheet_without_foundation(self) -> None:
        # 基礎要素が無ければ基礎伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_sheet_commands(empty) == []

    def test_foundation_plan_sheet_from_fixture(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_sheet_commands(ifc)
        assert len(sheets) == 1
        command = sheets[0]
        assert command['number'] == '1'
        assert command['title'] == '基礎伏図'

    def test_viewport_shows_foundation_and_grid_layers(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        viewport = sheet.build_sheet_commands(ifc)[0]['viewport']
        assert viewport['drawing_title'] == '基礎伏図'
        assert viewport['drawing_number'] == '1'
        # 底盤・立上り・アンカーボルト・通り芯の順で表示する
        assert viewport['layers'] == [
            'F-底盤', 'F-立上り', 'F-アンカーボルト', '共通']
