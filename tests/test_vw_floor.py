"""描画フェーズ (vw.floor) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import FloorCommand


def make_command() -> FloorCommand:
    return {
        'layer': '1-FL',
        'class': '04構造-02木造-06耐力面材-02床',
        'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0], [0.0, 2000.0]],
        'thickness': 24.0,
        'elevation': 425.0,
        'bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
    }


def _make_vs_mock(existing_layers: set[str], floor_handle: object) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.LNewObj.return_value = floor_handle
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.floor as vw_floor
        importlib.reload(vw_floor)
        return vw_floor


class TestExecuteFloors:
    def test_creates_floor_with_tool(self) -> None:
        floor_h = object()
        vs_mock = _make_vs_mock({'1-FL'}, floor_h)
        vw_floor = _load(vs_mock)

        count = vw_floor.execute_floors([make_command()])

        assert count == 1
        # アクティブレイヤを 1-FL に切り替える
        vs_mock.Layer.assert_called_once_with('1-FL')
        # 床ツール: BeginFloor(厚み) → 外形 → EndGroup で確定
        vs_mock.BeginFloor.assert_called_once_with(24.0)
        vs_mock.EndGroup.assert_called_once()
        # 外形の頂点を MoveTo/LineTo で描く(4 頂点 → MoveTo 1 + LineTo 3)
        assert vs_mock.MoveTo.call_count == 1
        assert vs_mock.LineTo.call_count == 3

    def test_positions_bottom_at_beam_top_and_binds(self) -> None:
        floor_h = object()
        vs_mock = _make_vs_mock({'1-FL'}, floor_h)
        vw_floor = _load(vs_mock)

        vw_floor.execute_floors([make_command()])

        # 床下端を横架材天端(絶対 Z=425)へ移動する
        vs_mock.Move3D.assert_called_once_with(0.0, 0.0, 425.0)
        # クラスを設定する
        vs_mock.SetClass.assert_called_once_with(floor_h, '04構造-02木造-06耐力面材-02床')
        # 高さ基準を横架材天端レベルにバインドする(boundType=2=Story、index 0)
        vs_mock.SetObjectStoryBound.assert_called_once_with(
            floor_h, 0, 2, 0, '横架材天端', 0.0)
        vs_mock.ResetObject.assert_called_once_with(floor_h)

    def test_skips_when_layer_missing(self) -> None:
        floor_h = object()
        vs_mock = _make_vs_mock(set(), floor_h)
        vw_floor = _load(vs_mock)

        count = vw_floor.execute_floors([make_command()])

        assert count == 0
        vs_mock.BeginFloor.assert_not_called()

    def test_places_multiple_floors(self) -> None:
        floor_h = object()
        vs_mock = _make_vs_mock({'1-FL', '2-FL'}, floor_h)
        vw_floor = _load(vs_mock)

        commands = [make_command(), make_command()]
        commands[1]['layer'] = '2-FL'

        count = vw_floor.execute_floors(commands)

        assert count == 2
        assert vs_mock.BeginFloor.call_count == 2

    def test_fallback_to_polygon_when_floor_not_created(self) -> None:
        # 床が作れない(LNewObj が NIL ハンドルを返す)場合は外形ポリゴンにフォールバック
        vs_mock = MagicMock()
        null_handle = object()
        vs_mock.Handle.return_value = null_handle
        vs_mock.GetObject.side_effect = lambda name: (
            'HANDLE_' + name if name == '1-FL' else null_handle)
        vs_mock.LNewObj.return_value = null_handle
        vw_floor = _load(vs_mock)

        count = vw_floor.execute_floors([make_command()])

        assert count == 1
        # フォールバックでもクラスは設定する(ポリゴンハンドル=NIL に対して呼ばれる)
        vs_mock.SetClass.assert_called_once_with(null_handle, '04構造-02木造-06耐力面材-02床')
        # 高さ移動・バインドはフォールバックでは行わない
        vs_mock.Move3D.assert_not_called()
        vs_mock.SetObjectStoryBound.assert_not_called()
