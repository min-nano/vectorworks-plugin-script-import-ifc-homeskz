"""描画フェーズ (vw.sheet) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import SheetCommand

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
        vs_mock.UpdateVP.assert_called_once_with('VP_HANDLE')

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
        # 対象外レイヤは非表示 (2) のみで、表示 (0) にはしない
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
