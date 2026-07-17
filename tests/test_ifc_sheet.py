"""解析フェーズ (ifc.sheet) のテスト。

基礎の有無に応じた基礎伏図シートと、各階の柱梁伏図シートの命令が組み立てられる
ことを、空の IFC と実 IFC フィクスチャで検証する。vs 非依存。
"""
from __future__ import annotations

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.document import AnchorBoltCommand
from vectorworks_plugin_import_ifc_homeskz.ifc import sheet

from tests.conftest import load_fixture_ifc


def _open(filename: str) -> ifcopenshell.file:
    return load_fixture_ifc(filename)


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


class TestSpanLayersAtCut:
    """切断レベルで span レイヤを絞るヘルパー(写り込み解消の中核)を直接検証する。"""

    # 2 階建て(1階・2階・屋根)の span レイヤ:
    # 1to2=1階管柱, 2to2.5=下屋束, 2to3=2階管柱, 3to3.5=主屋根束, 1to3=通し柱
    SPANS = [
        (1.0, 2.0, '1to2-柱'),
        (1.0, 3.0, '1to3-柱'),
        (2.0, 2.5, '2to2.5-柱'),
        (2.0, 3.0, '2to3-柱'),
        (3.0, 3.5, '3to3.5-柱'),
    ]

    def test_first_floor_cut_shows_first_floor_and_through(self) -> None:
        # 1 階床伏図(切断 1.25): 1階管柱と通し柱
        assert sheet._span_layers_at_cut(self.SPANS, 1.25) == ['1to2-柱', '1to3-柱']

    def test_second_floor_cut_shows_second_floor_and_dormer_and_through(self) -> None:
        # 2 階床伏図(切断 2.25): 通し柱・下屋束・2階管柱(1階管柱 1to2 は 2.25 を含まない)
        assert sheet._span_layers_at_cut(self.SPANS, 2.25) == [
            '1to3-柱', '2to2.5-柱', '2to3-柱']

    def test_roof_cut_excludes_dormer_koyazuka(self) -> None:
        # 2 階小屋伏図(切断 3.25): 主屋根束のみ。下屋束(2to2.5)は含まない=写り込み解消。
        # 通し柱 1to3(to=3)も 3.25 は含まないため出ない。
        assert sheet._span_layers_at_cut(self.SPANS, 3.25) == ['3to3.5-柱']

    def test_boundary_is_inclusive(self) -> None:
        # from ≤ cut ≤ to の境界は含む
        assert sheet._span_layers_at_cut([(2.0, 2.5, '2to2.5-柱')], 2.0) == ['2to2.5-柱']
        assert sheet._span_layers_at_cut([(2.0, 2.5, '2to2.5-柱')], 2.5) == ['2to2.5-柱']
        assert sheet._span_layers_at_cut([(2.0, 2.5, '2to2.5-柱')], 2.75) == []


class TestPlanMarkLayerBelowCut:
    """切断レベルの直下(to<切断)の伏図記号レイヤを返すヘルパーを検証する。"""

    SPANS = TestSpanLayersAtCut.SPANS

    def test_floor_cut_picks_integer_to_below(self) -> None:
        # 2 階床伏図(切断 2.25): 直下 to=2(1階管柱 1to2)→ 2-柱伏図記号
        assert sheet._plan_mark_layer_below_cut(self.SPANS, 2.25) == '2-柱伏図記号'

    def test_moya_cut_picks_half_level_to_below(self) -> None:
        # 1 階母屋伏図(切断 2.75): 直下 to=2.5(下屋束 2to2.5)→ 2.5-柱伏図記号
        assert sheet._plan_mark_layer_below_cut(self.SPANS, 2.75) == '2.5-柱伏図記号'

    def test_picks_greatest_to_strictly_below_cut(self) -> None:
        # 2 階小屋伏図(切断 3.25): to<3.25 の最大は 3(2to3・1to3)→ 3-柱伏図記号
        assert sheet._plan_mark_layer_below_cut(self.SPANS, 3.25) == '3-柱伏図記号'

    def test_none_when_no_span_below_cut(self) -> None:
        # 1 階床伏図(切断 1.25): to<1.25 の span は無い → 伏図記号レイヤ無し
        assert sheet._plan_mark_layer_below_cut(self.SPANS, 1.25) is None


class TestBuildFloorFramingSheetCommands:
    def test_no_sheet_without_stories(self) -> None:
        # ストーリが無ければ柱梁伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_floor_framing_sheet_commands(empty) == []

    def test_one_sheet_per_story(self) -> None:
        # フィクスチャは 2 階建て(1階・2階・屋根)なので 3 枚。下屋根の母屋は
        # 柱梁伏図には重ねず専用の母屋伏図に分けるため、柱梁伏図のタイトルに母屋の
        # 表記は付かない(最上階は 2階小屋伏図)。
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_floor_framing_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '1階床伏図', '2階床伏図', '2階小屋伏図']
        # シートレイヤ番号は基礎伏図(1)に続けて 2 から
        assert [s['number'] for s in sheets] == ['2', '3', '4']

    def test_first_floor_shows_beam_column_anchor_slab_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        first = sheet.build_floor_framing_sheet_commands(ifc)[0]
        assert first['title'] == '1階床伏図'
        assert first['viewport']['drawing_title'] == '1階床伏図'
        assert first['viewport']['drawing_number'] == '2'
        # 横架材・柱 span(切断 1.25 を含む 1to2)・アンカーボルト・床・通り芯の順
        assert first['viewport']['layers'] == [
            '1-横架材天端', '1to2-柱', 'F-アンカーボルト', '1-FL', '共通']

    def test_middle_floor_shows_beam_column_slab_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        middle = sheet.build_floor_framing_sheet_commands(ifc)[1]
        # 下屋根の母屋は専用の母屋伏図に分けるため、この階には母屋を重ねない
        assert middle['title'] == '2階床伏図'
        # 切断 2.25 を含む span=2 階起点の柱(2to3=2階管柱・2to2.5=下屋束の断面)・
        # 切断直下(to<2.25)の伏図記号 2-柱伏図記号(下階=1階管柱 1to2 の平面記号)・
        # 床・通り芯。下から届く通し柱があれば併せて出る。アンカーボルトは含まない。
        assert middle['viewport']['layers'] == [
            '2-横架材天端', '2to2.5-柱', '2to3-柱', '2-柱伏図記号', '2-FL', '共通']

    def test_roof_shows_beam_column_directly_below_grid(self) -> None:
        ifc = _open('伏図次郎【2階】.ifc')
        roof = sheet.build_floor_framing_sheet_commands(ifc)[-1]
        # 最上階は主屋根の階番号(2階小屋)を付ける。下屋根の母屋は専用の母屋伏図に
        # 分けるため小屋伏図には重ねない。
        assert roof['title'] == '2階小屋伏図'
        # 軒高の横架材・切断 3.25 を含む span(3to3.5=主屋根束の断面)・切断直下
        # (to<3.25)の伏図記号 3-柱伏図記号(2階管柱 2to3 の平面記号)・通り芯。
        # 下屋束(2to2.5、to=2.5)は切断 3.25 を含まないため写り込まない(解消)。
        assert roof['viewport']['layers'] == [
            'R-軒高', '3to3.5-柱', '3-柱伏図記号', '共通']


class TestBuildMoyaSheetCommands:
    def test_no_sheet_without_stories(self) -> None:
        # ストーリが無ければ母屋伏図シートは作らない
        empty = ifcopenshell.file()
        assert sheet.build_moya_sheet_commands(empty) == []

    def test_moya_sheet_from_fixture(self) -> None:
        # 屋根版を持つ階ごとに 1 枚。フィクスチャは 2 階の下屋根と屋根の主屋根なので
        # 2 枚(1階母屋伏図=下屋根・2階母屋伏図=主屋根)。番号は柱梁伏図(1階・2階・
        # 屋根=基礎に続く 2〜4)の次=5・6。
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_moya_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == ['1階母屋伏図', '2階母屋伏図']
        assert [s['number'] for s in sheets] == ['5', '6']
        # 下屋根(2階)の母屋伏図: 母屋・垂木・野地板・柱・通り芯。切断レベル(1+1.75=2.75)を
        # span が含む柱レイヤ=屋根を貫いて立ち上がる主屋の柱(2to3)。下屋の小屋束
        # (2to2.5、to=2.5<2.75)は載らない(小屋束の断面は母屋伏図に出さない)。
        assert sheets[0]['viewport']['drawing_title'] == '1階母屋伏図'
        assert sheets[0]['viewport']['drawing_number'] == '5'
        # 切断直下(to<2.75)の伏図記号は 2.5-柱伏図記号(下屋小屋束 2to2.5 の平面記号)。
        assert sheets[0]['viewport']['layers'] == [
            '2-母屋', '2-垂木', '2-野地板', '2to3-柱', '2.5-柱伏図記号', '共通']
        # 主屋根(屋根)の母屋伏図: 切断レベル(2+1.75=3.75)を span が含む柱は無い
        # (最上の柱 3to3.5 は to=3.5<3.75)ため柱レイヤは載らない。切断直下
        # (to<3.75)の伏図記号は 3.5-柱伏図記号(主屋根小屋束 3to3.5 の平面記号)。
        assert sheets[1]['viewport']['layers'] == [
            'R-母屋', 'R-垂木', 'R-野地板', '3.5-柱伏図記号', '共通']

    def test_roof_only_shed_dormer_has_no_moya_layer(self) -> None:
        # 母屋の無い下屋根(片流れ等)の母屋伏図は母屋レイヤを含まず、垂木・野地板・
        # 柱・通り芯を表示する(屋根版はあるため伏図自体は作る)。切断レベル
        # (1+1.75=2.75)を span が含む主屋の柱(1to3・2to3)を載せる。
        ifc = _open('スキップフロア_サンプル.ifc')
        sheets = sheet.build_moya_sheet_commands(ifc)
        # 2階の下屋根(母屋なし)と屋根の主屋根の 2 枚
        assert [s['title'] for s in sheets] == ['1階母屋伏図', '2階母屋伏図']
        # 切断直下(to<2.75)の伏図記号は 2-柱伏図記号(1階管柱 1to2 の平面記号)。
        assert sheets[0]['viewport']['layers'] == [
            '2-垂木', '2-野地板', '1to3-柱', '2to3-柱', '2-柱伏図記号', '共通']

    def test_moya_sheet_column_cut_levels(self) -> None:
        # 母屋伏図の柱の切断レベルは「その階の床レベル + 0.75」。1階母屋伏図(i=1)は
        # 2.75、2階母屋伏図(i=2)は 3.75 を含む柱レイヤを表示する。3 階建てフィクスチャで
        # 各母屋伏図が想定の span 柱レイヤ(屋根を貫く主屋の柱)を載せることを確認する。
        ifc = _open('グレー本モデルプラン1【3階】.ifc')
        sheets = {s['title']: s for s in sheet.build_moya_sheet_commands(ifc)}

        def column_layers(title: str) -> list[str]:
            return [
                layer for layer in sheets[title]['viewport']['layers']
                if layer.endswith('-柱')
            ]

        # 1階母屋伏図: 2.75 を span が含む柱(2to3・2to3.5)。
        assert column_layers('1階母屋伏図') == ['2to3-柱', '2to3.5-柱']
        # 2階母屋伏図: 3.75 を span が含む柱(3to4)。
        assert column_layers('2階母屋伏図') == ['3to4-柱']


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
        # 基礎伏図凡例スタイルを関連付ける
        assert legend['style'] == '基礎伏図凡例'
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


class TestBuildFloorLegendCommands:
    def test_no_legend_without_stories(self) -> None:
        # ストーリが無ければ柱梁伏図・母屋伏図が作られないため凡例も作らない
        empty = ifcopenshell.file()
        assert sheet.build_floor_legend_commands(empty) == []

    def test_one_legend_per_floor_and_moya_sheet(self) -> None:
        # 各柱梁伏図(床伏図・小屋伏図)・母屋伏図のシートレイヤに凡例を 1 つずつ置く。
        # 番号は対応する sheet 命令(床伏図・小屋伏図・母屋伏図)の番号に一致させる。
        ifc = _open('伏図次郎【2階】.ifc')
        legends = sheet.build_floor_legend_commands(ifc)
        floor_sheets = sheet.build_floor_framing_sheet_commands(ifc)
        moya_sheets = sheet.build_moya_sheet_commands(ifc)
        expected_numbers = (
            [s['number'] for s in floor_sheets]
            + [s['number'] for s in moya_sheets])
        assert [legend['number'] for legend in legends] == expected_numbers
        # 基礎伏図(番号 1)はこの関数の対象外(build_legend_commands が別途扱う)
        assert '1' not in [legend['number'] for legend in legends]

    def test_legends_use_floor_plan_style_and_no_items(self) -> None:
        # 床伏図凡例スタイルを関連付け、載せるシンボルはスタイルが決めるため items は空
        ifc = _open('伏図次郎【2階】.ifc')
        legends = sheet.build_floor_legend_commands(ifc)
        assert legends  # 伏図があるので凡例が組み立てられる
        for legend in legends:
            assert legend['style'] == '床伏図凡例'
            assert legend['items'] == []
            assert legend['position'] == [0.0, 0.0]


class TestBuildSheetCommands:
    def test_foundation_then_floor_framing_then_moya(self) -> None:
        # 基礎伏図に続けて各階の柱梁伏図が並び、最後に屋根版を持つ階ごとの母屋伏図
        # (下屋根=1階母屋伏図・主屋根=2階母屋伏図)が来る
        ifc = _open('伏図次郎【2階】.ifc')
        sheets = sheet.build_sheet_commands(ifc)
        assert [s['title'] for s in sheets] == [
            '基礎伏図', '1階床伏図', '2階床伏図', '2階小屋伏図',
            '1階母屋伏図', '2階母屋伏図']
        assert [s['number'] for s in sheets] == ['1', '2', '3', '4', '5', '6']
