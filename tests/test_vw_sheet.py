"""描画フェーズ (vw.sheet) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import SheetCommand, TagCommand

_NUMBER = '1'
_TITLE = '基礎伏図'
_TARGET_LAYERS = ['F-底盤', 'F-立上り', 'F-アンカーボルト', '共通']


def make_command() -> SheetCommand:
    return {
        'number': _NUMBER,
        'title': _TITLE,
        'viewport': {
            'drawing_title': _TITLE,
            'drawing_number': '1',
            'layers': list(_TARGET_LAYERS),
        },
    }


def make_floor_command(
    number: str = '2', title: str = '1階床伏図',
    layers: list[str] | None = None,
) -> SheetCommand:
    return {
        'number': number,
        'title': title,
        'viewport': {
            'drawing_title': title,
            'drawing_number': number,
            'layers': layers or ['1-横架材天端', '1-柱', '共通'],
        },
    }


def make_tag(layer: str = '1-横架材天端', member_index: int = 0) -> TagCommand:
    return {
        'style': '断面寸法',
        'layer': layer,
        'member_index': member_index,
        'position': [1000.0, 160.0],
        'angle': 0.0,
    }


def make_legend(number: str = '1', style: str = '基礎伏図凡例') -> dict[str, Any]:
    return {
        'number': number,
        'style': style,
        'position': [0.0, 0.0],
        'items': [
            {'symbol': 'アンカーボルト_M12', 'label': '土台用アンカーボルトM12'},
        ],
    }


def _handle(name: str) -> str:
    return 'HANDLE_' + name


def _make_vs_mock(
    design_layers: list[str], sheet_exists: bool = False,
    classes: list[str] | None = None,
) -> MagicMock:
    """デザインレイヤ列挙 (FLayer/NextLayer)・クラス列挙をモデル化した vs モック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    layer_handles = [_handle(n) for n in design_layers]
    class_names = classes or []

    def class_list(index: int) -> str:
        return class_names[index - 1]

    vs_mock.ClassNum.return_value = len(class_names)
    vs_mock.ClassList.side_effect = class_list

    def f_layer() -> object:
        return layer_handles[0] if layer_handles else null_handle

    def next_layer(layer_h: Any) -> object:
        if layer_h in layer_handles:
            i = layer_handles.index(layer_h)
            if i + 1 < len(layer_handles):
                return layer_handles[i + 1]
        return null_handle

    def get_layer_by_name(name: str) -> object:
        return _handle(name) if name in design_layers else null_handle

    def get_obj(name: str) -> object:
        # シートレイヤはシートレイヤ番号を名前として作る
        if sheet_exists and name == _NUMBER:
            return _handle(name)
        return null_handle

    def create_layer(name: str, layer_type: int) -> str:
        return _handle(name)

    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.GetLayerByName.side_effect = get_layer_by_name
    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateVP.return_value = 'VP_HANDLE'
    vs_mock.CreateCustomObject.return_value = 'TAG_HANDLE'
    vs_mock.CreateCustomObjectN.return_value = 'LEGEND_HANDLE'
    # デザインレイヤの縮尺(1:50 相当)
    vs_mock.GetLScale.return_value = 50.0
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.sheet as vw_sheet
        importlib.reload(vw_sheet)
        return vw_sheet


class TestExecuteSheets:
    def test_creates_sheet_layer_named_by_number_with_title(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        count = vw_sheet.execute_sheets([make_command()])

        assert count == 1
        # シートレイヤ番号はレイヤ名が担う: 番号を名前にプレゼンテーションレイヤ
        # (種別 2) として作る
        vs_mock.CreateLayer.assert_called_once_with(_NUMBER, 2)
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        # シートレイヤタイトルをオブジェクト変数で設定する
        assert (_handle(_NUMBER), vw_sheet._OV_SHEET_TITLE, _TITLE) in ov_calls

    def test_reuses_existing_sheet_layer(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS, sheet_exists=True)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        # 既存の同名シートレイヤがあれば作り直さない
        vs_mock.CreateLayer.assert_not_called()

    def test_creates_viewport_with_drawing_title_and_number(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        # ビューポートはシートレイヤ上に作る
        vs_mock.CreateVP.assert_called_once_with(_handle(_NUMBER))
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        assert ('VP_HANDLE', vw_sheet._OV_VP_DRAWING_TITLE, _TITLE) in ov_calls
        assert ('VP_HANDLE', vw_sheet._OV_VP_DRAWING_NUMBER, '1') in ov_calls
        # ビューを 2D/平面 に確定させる過程(force_plan_view)と最終描画で
        # UpdateVP が同じビューポートに呼ばれる
        update_calls = [c.args for c in vs_mock.UpdateVP.call_args_list]
        assert ('VP_HANDLE',) in update_calls

    def test_forces_plan_view_projection(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        # ビューを「上」にしたうえで Project 2D を OFF→更新→ON と切り替えて
        # 2D/平面 のキャッシュを作り直す(手動対処と同じトグル)
        vs_mock.SetObjectVariableInt.assert_any_call(
            'VP_HANDLE', vw_sheet._OV_VP_VIEW_TYPE, vw_sheet._VP_VIEW_TOP)
        bool_calls = [c.args for c in vs_mock.SetObjectVariableBoolean.call_args_list]
        assert bool_calls == [
            ('VP_HANDLE', vw_sheet._OV_VP_PROJECT_2D, False),
            ('VP_HANDLE', vw_sheet._OV_VP_PROJECT_2D, True),
        ]
        # Project 2D OFF のあと(3D「上」の描画)と最終描画で UpdateVP が 2 回呼ばれ、
        # 最終状態は Project 2D ON(=2D/平面)になる。
        update_calls = [c.args for c in vs_mock.UpdateVP.call_args_list]
        assert update_calls == [('VP_HANDLE',), ('VP_HANDLE',)]

    def test_shows_only_target_layers(self) -> None:
        extras = ['1-FL', '1-横架材天端']
        vs_mock = _make_vs_mock(_TARGET_LAYERS + extras)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        vis_calls = [c.args for c in vs_mock.SetVPLayerVisibility.call_args_list]
        # 対象レイヤの最終的な表示種別は表示 (0)
        for name in _TARGET_LAYERS:
            assert ('VP_HANDLE', _handle(name),
                    vw_sheet._VP_LAYER_VISIBLE) in vis_calls
        # 対象外レイヤは非表示 (1) のみで、表示 (0) にはしない
        for name in extras:
            assert ('VP_HANDLE', _handle(name),
                    vw_sheet._VP_LAYER_HIDDEN) in vis_calls
            assert ('VP_HANDLE', _handle(name),
                    vw_sheet._VP_LAYER_VISIBLE) not in vis_calls

    def test_shows_all_classes(self) -> None:
        classes = ['なし', '04構造-01基礎-03立ち上がり',
                   '01作図-01線-01基準線-01通り芯-X通り']
        vs_mock = _make_vs_mock(_TARGET_LAYERS, classes=classes)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        # 全クラスを表示 (0) に設定する
        cls_calls = [c.args for c in vs_mock.SetVPClassVisibility.call_args_list]
        for name in classes:
            assert ('VP_HANDLE', name, vw_sheet._VP_CLASS_VISIBLE) in cls_calls

    def test_hides_named_classes(self) -> None:
        rebar = '04構造-01基礎-09鉄筋'
        classes = ['なし', '04構造-01基礎-03立ち上がり', rebar]
        vs_mock = _make_vs_mock(_TARGET_LAYERS, classes=classes)
        vw_sheet = _load(vs_mock)

        command = make_command()
        command['viewport']['hidden_classes'] = [rebar]
        vw_sheet.execute_sheets([command])

        cls_calls = [c.args for c in vs_mock.SetVPClassVisibility.call_args_list]
        # hidden_classes に挙げた配筋クラスは非表示 (1) にする
        assert ('VP_HANDLE', rebar, vw_sheet._VP_CLASS_HIDDEN) in cls_calls
        assert ('VP_HANDLE', rebar, vw_sheet._VP_CLASS_VISIBLE) not in cls_calls
        # それ以外のクラスは従来どおり表示 (0)
        for name in ['なし', '04構造-01基礎-03立ち上がり']:
            assert ('VP_HANDLE', name, vw_sheet._VP_CLASS_VISIBLE) in cls_calls
            assert ('VP_HANDLE', name, vw_sheet._VP_CLASS_HIDDEN) not in cls_calls

    def test_matches_viewport_scale_to_design_layer(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        # 表示デザインレイヤの縮尺 (GetLScale) をビューポート縮尺に設定する
        vs_mock.SetObjectVariableReal.assert_called_once_with(
            'VP_HANDLE', vw_sheet._OV_VP_SCALE, 50.0)

    def test_skips_viewport_when_creation_fails(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vs_mock.CreateVP.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        count = vw_sheet.execute_sheets([make_command()])

        # シート自体は作成扱い、ビューポート設定は行わない
        assert count == 1
        vs_mock.UpdateVP.assert_not_called()


class TestExecuteSheetsWithTags:
    def test_places_tag_on_matching_floor_viewport(self) -> None:
        vs_mock = _make_vs_mock(['1-横架材天端', '1-柱', '共通'])
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_floor_command()], [make_tag()],
            {0: 'MEMBER_HANDLE'}, counters)

        # データタグを挿入位置・角度で作成する
        vs_mock.CreateCustomObject.assert_called_once_with(
            vw_sheet._DATA_TAG_PLUGIN, (1000.0, 160.0), 0.0)
        # スタイルを関連付け、対象横架材に関連付け、ビューポート注釈に追加する
        vs_mock.SetPluginStyle.assert_called_once_with('TAG_HANDLE', '断面寸法')
        # 引出線を表示するパラメータを OFF にする
        vs_mock.SetRField.assert_called_once_with(
            'TAG_HANDLE', vw_sheet._DATA_TAG_PLUGIN,
            vw_sheet._LEADER_FIELD, vw_sheet._LEADER_OFF)
        vs_mock.DT_AssociateWithObj.assert_called_once_with(
            'TAG_HANDLE', 'MEMBER_HANDLE')
        vs_mock.AddVPAnnotationObject.assert_called_once_with(
            'VP_HANDLE', 'TAG_HANDLE')
        assert counters['tags'] == 1

    def test_tag_not_placed_on_non_matching_viewport(self) -> None:
        # 基礎伏図(横架材レイヤを表示しない)には横架材タグを置かない
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command()], [make_tag()], {0: 'MEMBER_HANDLE'}, counters)

        vs_mock.CreateCustomObject.assert_not_called()
        assert counters['tags'] == 0

    def test_tag_routed_to_its_own_floor_only(self) -> None:
        # 2 枚の伏図があるとき、タグはレイヤが一致するビューポートにのみ載る
        vs_mock = _make_vs_mock(['1-横架材天端', '2-横架材天端', '共通'])
        vw_sheet = _load(vs_mock)

        sheets = [
            make_floor_command('2', '1階床伏図', ['1-横架材天端', '共通']),
            make_floor_command('3', '2階床伏図', ['2-横架材天端', '共通']),
        ]
        tags = [make_tag('1-横架材天端', 0), make_tag('2-横架材天端', 1)]
        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            sheets, tags, {0: 'M0', 1: 'M1'}, counters)

        # タグ 2 つがそれぞれ 1 回ずつ配置される
        assert counters['tags'] == 2
        assoc = [c.args for c in vs_mock.DT_AssociateWithObj.call_args_list]
        assert ('TAG_HANDLE', 'M0') in assoc
        assert ('TAG_HANDLE', 'M1') in assoc

    def test_tag_placed_without_member_handle_skips_association(self) -> None:
        # 対象横架材のハンドルが無い(フォールバック描画等)場合は関連付けを省く
        vs_mock = _make_vs_mock(['1-横架材天端', '共通'])
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_floor_command(layers=['1-横架材天端', '共通'])],
            [make_tag()], {}, counters)

        # タグ自体は配置するが、関連付けは行わない
        vs_mock.CreateCustomObject.assert_called_once()
        vs_mock.DT_AssociateWithObj.assert_not_called()
        assert counters['tags'] == 1

    def test_no_tags_when_tag_list_empty(self) -> None:
        vs_mock = _make_vs_mock(['1-横架材天端', '共通'])
        vw_sheet = _load(vs_mock)

        count = vw_sheet.execute_sheets([make_floor_command()])

        assert count == 1
        vs_mock.CreateCustomObject.assert_not_called()

    def test_tag_not_counted_when_creation_fails(self) -> None:
        # データタグが作れない場合はカウントせず関連付けもしない
        vs_mock = _make_vs_mock(['1-横架材天端', '共通'])
        vs_mock.CreateCustomObject.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_floor_command(layers=['1-横架材天端', '共通'])],
            [make_tag()], {0: 'MEMBER_HANDLE'}, counters)

        assert counters['tags'] == 0
        vs_mock.DT_AssociateWithObj.assert_not_called()

    def test_no_tag_when_sheet_layer_creation_fails(self) -> None:
        # シートレイヤ(=ビューポート)が作れない場合はタグを載せない
        vs_mock = _make_vs_mock(['1-横架材天端', '共通'])
        vs_mock.CreateLayer.side_effect = None
        vs_mock.CreateLayer.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        count = vw_sheet.execute_sheets(
            [make_floor_command(layers=['1-横架材天端', '共通'])],
            [make_tag()], {0: 'MEMBER_HANDLE'}, counters)

        # シートは作成扱いだがタグは配置されない
        assert count == 1
        assert counters['tags'] == 0
        vs_mock.CreateCustomObject.assert_not_called()


class TestExecuteSheetsWithLegends:
    def test_places_legend_on_matching_sheet(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command()], legends=[make_legend()], counters=counters)

        # 配置先シートレイヤ(番号 1)をアクティブにしてグラフィック凡例 PIO を
        # 挿入位置・showPref=False で作る
        vs_mock.Layer.assert_any_call('1')
        vs_mock.CreateCustomObjectN.assert_called_once_with(
            vw_sheet._GRAPHIC_LEGEND_PLUGIN, (0.0, 0.0), 0, False)
        # ソース定義(シンボル + 基礎伏図ビューポートフィルタ)を持つプラグイン
        # スタイルを関連付ける
        vs_mock.SetPluginStyle.assert_any_call(
            'LEGEND_HANDLE', vw_sheet._GRAPHIC_LEGEND_STYLE)
        # 箱幅を既定値に設定して可視化し(サイズ 0 でハンドルを掴めないのを防ぐ)、
        # ResetObject で反映する
        vs_mock.SetRField.assert_called_once_with(
            'LEGEND_HANDLE', vw_sheet._GRAPHIC_LEGEND_PLUGIN,
            vw_sheet._LEGEND_WIDTH_FIELD, vw_sheet._LEGEND_BOX_WIDTH)
        vs_mock.ResetObject.assert_any_call('LEGEND_HANDLE')
        # クラスでは見た目を制御できないため、線の太さ(0.13mm)・塗り(なし)を
        # オブジェクトの属性として直接設定する
        vs_mock.SetLW.assert_any_call(
            'LEGEND_HANDLE', vw_sheet._LEGEND_LINE_WEIGHT_MILS)
        vs_mock.SetFPat.assert_any_call(
            'LEGEND_HANDLE', vw_sheet._LEGEND_FILL_NONE)
        # 全配置後にスタイルからセル(シンボル)を再計算してインスタンスへ反映する
        vs_mock.UpdateStyledObjects.assert_called_once_with(
            vw_sheet._GRAPHIC_LEGEND_STYLE)
        assert counters['legends'] == 1

    def test_uses_command_style_and_updates_each_style_once(self) -> None:
        # 基礎伏図凡例(基礎伏図)と床伏図凡例(床伏図)を別スタイルで配置し、
        # 各スタイルにつき UpdateStyledObjects を 1 回ずつ呼ぶ
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command(), make_floor_command()],
            legends=[
                make_legend('1', '基礎伏図凡例'),
                make_legend('2', '床伏図凡例'),
            ],
            counters=counters)

        # 命令の style をそのまま関連付ける(基礎伏図凡例・床伏図凡例)
        vs_mock.SetPluginStyle.assert_any_call('LEGEND_HANDLE', '基礎伏図凡例')
        vs_mock.SetPluginStyle.assert_any_call('LEGEND_HANDLE', '床伏図凡例')
        # 使用した各スタイルにつき 1 回ずつ再計算する
        styles = {
            call.args[0] for call in vs_mock.UpdateStyledObjects.call_args_list}
        assert styles == {'基礎伏図凡例', '床伏図凡例'}
        assert vs_mock.UpdateStyledObjects.call_count == 2
        assert counters['legends'] == 2

    def test_sets_line_weight_and_no_fill_attributes(self) -> None:
        # クラスでは見た目を制御できないため、線の太さ(0.13mm=5 ミル)・塗り(なし=0)を
        # オブジェクトの属性として直接設定する
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()], legends=[make_legend()])

        vs_mock.SetLW.assert_any_call('LEGEND_HANDLE', 5)
        vs_mock.SetFPat.assert_any_call('LEGEND_HANDLE', 0)

    def test_legend_not_placed_on_non_matching_sheet(self) -> None:
        # シートレイヤ番号が一致しない凡例は載せない
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command()], legends=[make_legend('2')], counters=counters)

        vs_mock.CreateCustomObjectN.assert_not_called()
        # 凡例を 1 つも置かなければスタイル更新も呼ばない
        vs_mock.UpdateStyledObjects.assert_not_called()
        assert counters['legends'] == 0

    def test_no_legend_when_list_empty(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        vw_sheet.execute_sheets([make_command()])

        vs_mock.CreateCustomObjectN.assert_not_called()

    def test_legend_not_counted_when_creation_fails(self) -> None:
        # PIO が作れない(プラグイン未登録等)場合はカウントしない
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vs_mock.CreateCustomObjectN.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command()], legends=[make_legend()], counters=counters)

        assert counters['legends'] == 0

    def test_no_legend_when_sheet_layer_creation_fails(self) -> None:
        # シートレイヤが作れない場合は凡例を載せない
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vs_mock.CreateLayer.side_effect = None
        vs_mock.CreateLayer.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        counters: dict[str, int] = {}
        vw_sheet.execute_sheets(
            [make_command()], legends=[make_legend()], counters=counters)

        assert counters['legends'] == 0
        vs_mock.CreateCustomObjectN.assert_not_called()
