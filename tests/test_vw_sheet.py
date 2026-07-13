"""描画フェーズ (vw.sheet) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import SheetCommand

_TITLE = '基礎伏図'
_TARGET_LAYERS = ['F-底盤', 'F-立上り', 'F-アンカーボルト', '共通']


def make_command() -> SheetCommand:
    return {
        'number': '1',
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
) -> MagicMock:
    """デザインレイヤ列挙 (FLayer/NextLayer) をモデル化した vs モック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    layer_handles = [_handle(n) for n in design_layers]

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
        if sheet_exists and name == _TITLE:
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
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.sheet as vw_sheet
        importlib.reload(vw_sheet)
        return vw_sheet


class TestExecuteSheets:
    def test_creates_sheet_layer_with_number_and_title(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vw_sheet = _load(vs_mock)

        count = vw_sheet.execute_sheets([make_command()])

        assert count == 1
        # シートレイヤはプレゼンテーションレイヤ (種別 2) として作る
        vs_mock.CreateLayer.assert_called_once_with(_TITLE, 2)
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        # シートレイヤ番号・タイトルをオブジェクト変数で設定する
        assert (_handle(_TITLE), vw_sheet._OV_SHEET_NUMBER, '1') in ov_calls
        assert (_handle(_TITLE), vw_sheet._OV_SHEET_TITLE, _TITLE) in ov_calls

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
        vs_mock.CreateVP.assert_called_once_with(_handle(_TITLE))
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

    def test_skips_viewport_when_creation_fails(self) -> None:
        vs_mock = _make_vs_mock(_TARGET_LAYERS)
        vs_mock.CreateVP.return_value = vs_mock.Handle(0)
        vw_sheet = _load(vs_mock)

        count = vw_sheet.execute_sheets([make_command()])

        # シート自体は作成扱い、ビューポート設定は行わない
        assert count == 1
        vs_mock.UpdateVP.assert_not_called()
