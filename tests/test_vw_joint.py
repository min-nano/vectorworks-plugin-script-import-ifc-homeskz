"""描画フェーズ (vw.joint) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import JointCommand


def make_command() -> JointCommand:
    return {
        'layer': '1-横架材天端',
        'symbol': '仕口',
        'position': [1500.0, 60.0],
        'angle': 90.0,
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
        import vectorworks_plugin_import_ifc_homeskz.vw.joint as vw_joint
        importlib.reload(vw_joint)
        return vw_joint


class TestExecuteJoints:
    def test_places_symbol_at_beam_end_with_angle(self) -> None:
        vs_mock = _make_vs_mock({'1-横架材天端'})
        vw_joint = _load(vs_mock)

        count = vw_joint.execute_joints([make_command()])

        assert count == 1
        # アクティブレイヤを横架材レイヤに切り替えてからシンボルを配置する
        vs_mock.Layer.assert_called_once_with('1-横架材天端')
        args = vs_mock.Symbol.call_args.args
        # vs.Symbol(symbolName, p, rotationAngle): p は基準点 POINT、回転は angle
        assert args[0] == '仕口'
        assert args[1] == (1500.0, 60.0)
        assert args[2] == 90.0

    def test_uses_moya_layer(self) -> None:
        vs_mock = _make_vs_mock({'R-母屋'})
        vw_joint = _load(vs_mock)

        command = make_command()
        command['layer'] = 'R-母屋'
        count = vw_joint.execute_joints([command])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('R-母屋')

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_joint = _load(vs_mock)

        count = vw_joint.execute_joints([make_command()])

        assert count == 0
        vs_mock.Symbol.assert_not_called()
