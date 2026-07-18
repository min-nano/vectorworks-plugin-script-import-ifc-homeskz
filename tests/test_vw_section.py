"""描画フェーズ (vw.section) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import SectionCommand

_NUMBER = '6'
_TITLE = '断面図'


def make_command() -> SectionCommand:
    return {
        'number': _NUMBER,
        'title': _TITLE,
        'drawing_title': _TITLE,
        'drawing_number': _NUMBER,
        'scale': 100.0,
        'line_start': [0.0, -9000.0],
        'line_end': [0.0, 9000.0],
        'look': [-1000.0, 0.0],
        'depth': 20000.0,
        'start_height': -1000.0,
        'end_height': 9000.0,
        'position': [0.0, 0.0],
    }


def _handle(name: str) -> str:
    return 'HANDLE_' + name


def _make_vs_mock(
    design_layers: list[str] | None = None,
    sheet_exists: bool = False,
    layer_creatable: bool = True,
) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle
    design_layers = design_layers or ['1-横架材天端', '共通']
    layer_handles = [_handle(n) for n in design_layers]

    def f_layer() -> object:
        return layer_handles[0] if layer_handles else null_handle

    def next_layer(layer_h: Any) -> object:
        if layer_h in layer_handles:
            i = layer_handles.index(layer_h)
            if i + 1 < len(layer_handles):
                return layer_handles[i + 1]
        return null_handle

    def get_obj(name: str) -> object:
        if sheet_exists and name == _NUMBER:
            return _handle(name)
        return null_handle

    def create_layer(name: str, layer_type: int) -> object:
        return _handle(name) if layer_creatable else null_handle

    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.ClassNum.return_value = 0
    vs_mock.CreateSectionViewport.return_value = 'SECTION_VP'
    vs_mock.CreateVP.return_value = 'FALLBACK_VP'
    vs_mock.GetBBox.return_value = ((0.0, 0.0), (0.0, 0.0))
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.section as vw_section
        importlib.reload(vw_section)
        return vw_section


class TestExecuteSections:
    def test_creates_sheet_layer_named_by_number_with_title(self) -> None:
        vs_mock = _make_vs_mock()
        vw_section = _load(vs_mock)

        count = vw_section.execute_sections([make_command()])

        assert count == 1
        # シートレイヤ番号はレイヤ名が担う(プレゼンテーションレイヤ=種別 2)
        vs_mock.CreateLayer.assert_called_once_with(_NUMBER, 2)
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        assert (_handle(_NUMBER), vw_section._OV_SHEET_TITLE, _TITLE) in ov_calls

    def test_reuses_existing_sheet_layer(self) -> None:
        vs_mock = _make_vs_mock(sheet_exists=True)
        vw_section = _load(vs_mock)

        vw_section.execute_sections([make_command()])

        vs_mock.CreateLayer.assert_not_called()

    def test_uses_create_section_viewport_with_line_geometry(self) -> None:
        vs_mock = _make_vs_mock()
        vw_section = _load(vs_mock)

        vw_section.execute_sections([make_command()])

        # 切断線 2 点・視線方向の第 3 点・深さ・鉛直クリップ・シートレイヤを渡す
        vs_mock.CreateSectionViewport.assert_called_once_with(
            (0.0, -9000.0), (0.0, 9000.0), (-1000.0, 0.0),
            20000.0, -1000.0, 9000.0, _handle(_NUMBER))
        # 側面ビューのフォールバックは使わない
        vs_mock.CreateVP.assert_not_called()
        # 縮尺・図面タイトル・図番を設定する
        vs_mock.SetObjectVariableReal.assert_any_call(
            'SECTION_VP', vw_section._OV_VP_SCALE, 100.0)
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        assert ('SECTION_VP', vw_section._OV_VP_DRAWING_TITLE, _TITLE) in ov_calls
        assert ('SECTION_VP', vw_section._OV_VP_DRAWING_NUMBER, _NUMBER) in ov_calls
        vs_mock.UpdateVP.assert_called_with('SECTION_VP')

    def test_falls_back_to_elevation_view_when_function_missing(self) -> None:
        vs_mock = _make_vs_mock()
        # 断面関数が無い環境を再現する(MagicMock から属性を削除)
        del vs_mock.CreateSectionViewport
        vw_section = _load(vs_mock)

        count = vw_section.execute_sections([make_command()])

        assert count == 1
        # 側面ビューを CreateVP + SetViewMatrix で作る
        vs_mock.CreateVP.assert_called_once_with(_handle(_NUMBER))
        # offX = -(切断線の最大 Y)=-9000、offZ = -(切断線の X)=0、回転 -90,-90,0
        vs_mock.SetViewMatrix.assert_called_once_with(
            'FALLBACK_VP', -9000.0, 0.0, -0.0, -90.0, -90.0, 0.0)

    def test_skips_when_sheet_layer_cannot_be_created(self) -> None:
        vs_mock = _make_vs_mock(layer_creatable=False)
        vw_section = _load(vs_mock)

        count = vw_section.execute_sections([make_command()])

        assert count == 0
        vs_mock.CreateSectionViewport.assert_not_called()

    def test_empty_commands_return_zero(self) -> None:
        vs_mock = _make_vs_mock()
        vw_section = _load(vs_mock)

        assert vw_section.execute_sections([]) == 0
