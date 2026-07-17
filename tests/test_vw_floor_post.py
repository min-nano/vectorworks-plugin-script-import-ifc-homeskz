"""描画フェーズ (vw.floor_post) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import FloorPostCommand


def make_command() -> FloorPostCommand:
    return {
        'layer': 'F-床束',
        'symbol': '床束',
        'position': [910.0, -455.0],
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
        import vectorworks_plugin_import_ifc_homeskz.vw.floor_post as vw_floor
        importlib.reload(vw_floor)
        return vw_floor


class TestExecuteFloorPosts:
    def test_places_symbol_at_position(self) -> None:
        vs_mock = _make_vs_mock({'F-床束'})
        vw_floor = _load(vs_mock)

        count = vw_floor.execute_floor_posts([make_command()])

        assert count == 1
        # アクティブレイヤを F-床束 に切り替えてからシンボルを配置する
        vs_mock.Layer.assert_called_once_with('F-床束')
        args = vs_mock.Symbol.call_args.args
        # vs.Symbol(symbolName, p, rotationAngle): p は 2D 座標の POINT、回転 0
        assert args[0] == '床束'
        assert args[1] == (910.0, -455.0)
        assert args[2] == 0

    def test_places_multiple_posts(self) -> None:
        vs_mock = _make_vs_mock({'F-床束'})
        vw_floor = _load(vs_mock)

        commands = [make_command(), make_command()]
        commands[1]['position'] = [1820.0, -455.0]

        count = vw_floor.execute_floor_posts(commands)

        assert count == 2
        assert vs_mock.Symbol.call_count == 2

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_floor = _load(vs_mock)

        count = vw_floor.execute_floor_posts([make_command()])

        assert count == 0
        vs_mock.Symbol.assert_not_called()
