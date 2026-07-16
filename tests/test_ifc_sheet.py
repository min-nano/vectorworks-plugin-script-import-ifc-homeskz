"""解析フェーズ (ifc.sheet) のテスト。

基礎の有無に応じた基礎伏図シートと、各階の柱梁伏図シートの命令が組み立てられる
ことを、空の IFC と実 IFC フィクスチャで検証する。vs 非依存。
"""
from __future__ import annotations

import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.document import AnchorBoltCommand
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
        # 底盤・立上り・床束・アンカーボルト・通り芯の順で表示する
        assert viewport['layers'] == [
            'F-底盤', 'F-立上り', 'F-床束', 'F-アンカーボルト', '共通']

    def test_viewport_hides_rebar_class(self) -> None:
        # 配筋は立上り・底盤と同じレイヤに重なるためレイヤでは絞れない。基礎伏図では
        # 配筋クラスをビューポート単位で非表示にする(断面でのみ表示する要件)。
        ifc = _open('伏図次郎【2階】.ifc')
        viewport = sheet.build_foundation_sheet_commands(ifc)[0]['viewport']
        assert viewport['hidden_classes'] == ['04構造-01基礎-09鉄筋']

    def test_floor_framing_viewport_hides_no_class(self) -> None:
        # 柱梁伏図は配筋を隠さない(基礎伏図のみ配筋を非表示にする)
        ifc = _open('伏図次郎【2階】.ifc')
        for command in sheet.build_floor_framing_sheet_commands(ifc):
            assert 'hidden_classes' not in command['viewport']


class TestBuildFloorFramingSheetCommands:
    def test_no_sheet_without_stories(self) -> None:
        # ストーリが無ければ柱梁伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_floor_framing_sheet_commands(empty) == []

    def test_one_sheet_per_story(self) -> None:
        # フィクスチャは 2 階建て(1階・2階・屋根)なので 3 枚。2階の下屋根の母屋
        # (下屋)は 1 つ上の最上階の伏図に載せるため、最上階が 2階小屋・1階母屋伏図
        # になり、2階の伏図には母屋が載らない(2階床伏図)。
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_floor_framing_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '1階床伏図', '2階床伏図', '2階小屋・1階母屋伏図']
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
        # 2階の下屋根の母屋は 1 つ上の階に載せるため、この階には母屋を重ねない
        assert middle['title'] == '2階床伏図'
        # 中間階はアンカーボルトを含まない(横架材・柱・下階柱・床・通り芯)
        assert middle['viewport']['layers'] == [
            '2-横架材天端', '2-柱', '2-下階柱', '2-FL', '共通']

    def test_roof_shows_beam_column_below_moya_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        roof = sheet.build_floor_framing_sheet_commands(ifc)[-1]
        # 最上階は主屋根の階番号(2階小屋)を付け、直下階(2階)の下屋根の母屋を重ねる
        assert roof['title'] == '2階小屋・1階母屋伏図'
        # 軒高の横架材・柱(束)・下階柱・直下階の母屋・垂木・通り芯(床は無い)
        assert roof['viewport']['layers'] == [
            'R-軒高', 'R-柱', 'R-下階柱', '2-母屋', '2-垂木', '共通']


class TestBuildMoyaSheetCommands:
    def test_no_sheet_without_stories(self) -> None:
        # ストーリが無ければ母屋伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_moya_sheet_commands(empty) == []

    def test_moya_sheet_from_fixture(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_moya_sheet_commands(ifc)
        assert len(sheets) == 1
        command = sheets[0]
        # 基礎伏図(1)+各階柱梁伏図(1階・2階・屋根=3)の次=5
        assert command['number'] == '5'
        # 主屋根が架かる最上階の階番号(2階建て=2)を付ける
        assert command['title'] == '2階母屋伏図'
        # 表示レイヤは母屋・垂木・小屋束記号・通り芯
        assert command['viewport']['drawing_title'] == '2階母屋伏図'
        assert command['viewport']['drawing_number'] == '5'
        assert command['viewport']['layers'] == [
            'R-母屋', 'R-垂木', 'R-小屋束', '共通']


def _anchor_bolt(symbol: str) -> AnchorBoltCommand:
    return {'layer': 'F-アンカーボルト', 'symbol': symbol, 'position': [0.0, 0.0]}


class TestBuildLegendCommands:
    def test_no_legend_without_foundation(self) -> None:
        # 基礎が無ければ基礎伏図が作られないため凡例も作らない
        empty = ifcopenshell.file()
        assert sheet.build_legend_commands(empty, []) == []

    def test_no_legend_without_anchor_bolt_symbols(self) -> None:
        # 基礎はあるがアンカーボルトが 1 本も無ければ載せるものが無く空
        ifc = _open('伏図次郎【2階】.ifc')
        assert sheet.build_legend_commands(ifc, []) == []

    def test_legend_lists_present_symbols_with_labels(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        anchor_bolts = [
            _anchor_bolt('アンカーボルト_M12'),
            _anchor_bolt('アンカーボルト_M16'),
        ]
        legends = sheet.build_legend_commands(ifc, anchor_bolts)
        assert len(legends) == 1
        legend = legends[0]
        # 基礎伏図(番号 1)のシートレイヤ上に配置する
        assert legend['number'] == '1'
        # M12→土台用・M16→ホールダウン用のラベル(固定マッピング)
        assert legend['items'] == [
            {'symbol': 'アンカーボルト_M12', 'label': '土台用アンカーボルトM12'},
            {'symbol': 'アンカーボルト_M16', 'label': 'ホールダウン用アンカーボルトM16'},
        ]

    def test_legend_includes_only_present_symbols(self) -> None:
        # M12 のみ配置されていれば M12 だけを載せる
        ifc = _open('伏図次郎【2階】.ifc')
        legend = sheet.build_legend_commands(
            ifc, [_anchor_bolt('アンカーボルト_M12')])[0]
        assert legend['items'] == [
            {'symbol': 'アンカーボルト_M12', 'label': '土台用アンカーボルトM12'},
        ]

    def test_legend_orders_m12_before_m16(self) -> None:
        # 入力順が M16→M12 でも並びは M12→M16(重複入力も 1 行にまとめる)
        ifc = _open('伏図次郎【2階】.ifc')
        anchor_bolts = [
            _anchor_bolt('アンカーボルト_M16'),
            _anchor_bolt('アンカーボルト_M12'),
            _anchor_bolt('アンカーボルト_M16'),
        ]
        legend = sheet.build_legend_commands(ifc, anchor_bolts)[0]
        assert [item['symbol'] for item in legend['items']] == [
            'アンカーボルト_M12', 'アンカーボルト_M16']


class TestBuildSheetCommands:
    def test_foundation_then_floor_framing_then_moya(self) -> None:
        # 基礎伏図に続けて各階の柱梁伏図が並び、最後に母屋伏図が来る
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '基礎伏図', '1階床伏図', '2階床伏図', '2階小屋・1階母屋伏図', '2階母屋伏図']
        assert [s['number'] for s in sheets] == ['1', '2', '3', '4', '5']
