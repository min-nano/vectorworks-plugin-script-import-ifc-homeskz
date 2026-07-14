"""描画フェーズ (vw.fire_brace) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import FireBraceCommand


def make_command() -> FireBraceCommand:
    return {
        'layer': '2-横架材天端',
        'symbol': '鋼製火打',
        'position': [1200.0, -800.0],
        'angle': -45.0,
    }


def _make_vs_mock(existing_layers: set[str]) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.fire_brace as vw_fire
        importlib.reload(vw_fire)
        return vw_fire


class TestExecuteFireBraces:
    def test_places_symbol_at_base_point_with_angle(self) -> None:
        vs_mock = _make_vs_mock({'2-横架材天端'})
        vw_fire = _load(vs_mock)

        count = vw_fire.execute_fire_braces([make_command()])

        assert count == 1
        # アクティブレイヤを横架材レイヤに切り替えてからシンボルを配置する
        vs_mock.Layer.assert_called_once_with('2-横架材天端')
        args = vs_mock.Symbol.call_args.args
        # vs.Symbol(symbolName, p, rotationAngle): p は基準点 POINT、回転は angle
        assert args[0] == '鋼製火打'
        assert args[1] == (1200.0, -800.0)
        assert args[2] == -45.0

    def test_uses_eaves_layer_for_top_story(self) -> None:
        vs_mock = _make_vs_mock({'R-軒高'})
        vw_fire = _load(vs_mock)

        command = make_command()
        command['layer'] = 'R-軒高'
        count = vw_fire.execute_fire_braces([command])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('R-軒高')

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_fire = _load(vs_mock)

        count = vw_fire.execute_fire_braces([make_command()])

        assert count == 0
        vs_mock.Symbol.assert_not_called()
