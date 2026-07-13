"""描画フェーズ (vw.anchor_bolt) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import AnchorBoltCommand


def make_command() -> AnchorBoltCommand:
    return {
        'layer': 'F-アンカーボルト',
        'symbol': 'アンカーボルト_M12',
        'position': [1200.0, -800.0],
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
        import vectorworks_plugin_import_ifc_homeskz.vw.anchor_bolt as vw_anchor
        importlib.reload(vw_anchor)
        return vw_anchor


class TestExecuteAnchorBolts:
    def test_places_symbol_at_axis(self) -> None:
        vs_mock = _make_vs_mock({'F-アンカーボルト'})
        vw_anchor = _load(vs_mock)

        count = vw_anchor.execute_anchor_bolts([make_command()])

        assert count == 1
        # アクティブレイヤを F-アンカーボルトに切り替えてからシンボルを配置する
        vs_mock.Layer.assert_called_once_with('F-アンカーボルト')
        args = vs_mock.Symbol.call_args.args
        # vs.Symbol(symbolName, p, rotationAngle): p は軸芯座標の POINT、回転 0
        assert args[0] == 'アンカーボルト_M12'
        assert args[1] == (1200.0, -800.0)
        assert args[2] == 0

    def test_places_m16_symbol(self) -> None:
        vs_mock = _make_vs_mock({'F-アンカーボルト'})
        vw_anchor = _load(vs_mock)

        command = make_command()
        command['symbol'] = 'アンカーボルト_M16'
        vw_anchor.execute_anchor_bolts([command])

        assert vs_mock.Symbol.call_args.args[0] == 'アンカーボルト_M16'

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_anchor = _load(vs_mock)

        count = vw_anchor.execute_anchor_bolts([make_command()])

        assert count == 0
        vs_mock.Symbol.assert_not_called()
