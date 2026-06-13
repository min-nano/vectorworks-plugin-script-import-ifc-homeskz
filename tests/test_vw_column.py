"""描画フェーズ (vw.column) のテスト。vs をモックし手書きの column 命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Collection
from unittest.mock import MagicMock, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import ColumnCommand, StoryBound


def make_column_command(layer: str = '1-柱', plan_layer: str = '1-柱(伏図)',
                        column_type: str = '管柱',
                        position: tuple[float, float] = (0.0, 0.0),
                        width: float = 105.0, depth: float = 105.0,
                        height: float = 2844.0, elevation: float = 426.0,
                        bottom_bound: StoryBound | None = None,
                        top_bound: StoryBound | None = None) -> ColumnCommand:
    return {
        'layer': layer,
        'plan_layer': plan_layer,
        'column_type': column_type,
        'position': list(position),
        'width': width,
        'depth': depth,
        'height': height,
        'elevation': elevation,
        'bottom_bound': bottom_bound or {'story': 0, 'level': '横架材天端', 'offset': 1.0},
        'top_bound': top_bound or {'story': 1, 'level': '横架材天端', 'offset': -200.0},
    }


def _make_vs_mock(existing_layers: Collection[str] = ()) -> MagicMock:
    """execute_columns() 用 vs モック。

    existing_layers に含まれるレイヤ名は GetObject で非 null を返す。
    CreateCustomObject は非 null を返し (プラグイン利用可能)、
    SetRField / ResetObject の呼び出しを追跡できる。
    """
    vs_mock = MagicMock()
    null_handle = object()
    non_null_handle = object()
    vs_mock.Handle.return_value = null_handle
    vs_mock.LNewObj.return_value = non_null_handle
    vs_mock.CreateCustomObject.return_value = non_null_handle

    def get_obj(name: str) -> object:
        return non_null_handle if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    return vs_mock


def _run_execute_columns(vs_mock: MagicMock, commands: list[ColumnCommand]) -> int:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.column as vw_column
        importlib.reload(vw_column)
        return vw_column.execute_columns(commands)


class TestExecuteColumns:
    def test_empty_commands_return_zero(self) -> None:
        vs_mock = _make_vs_mock()
        count = _run_execute_columns(vs_mock, [])
        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_returns_count_of_drawn_columns(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        count = _run_execute_columns(vs_mock, [
            make_column_command(position=(0.0, 0.0)),
            make_column_command(position=(1000.0, 0.0)),
        ])
        assert count == 2

    def test_skips_command_when_layer_missing(self) -> None:
        """配置先レイヤが未生成の命令はスキップする（勝手にレイヤを作らない）。"""
        vs_mock = _make_vs_mock(existing_layers=set())
        count = _run_execute_columns(vs_mock, [make_column_command()])
        assert count == 0
        vs_mock.Layer.assert_not_called()
        vs_mock.CreateLayer.assert_not_called()

    def test_switches_to_command_layer(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-柱', 'R-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(layer='1-柱'),
            make_column_command(layer='R-柱'),
        ])
        layer_calls = [c.args[0] for c in vs_mock.Layer.call_args_list]
        assert '1-柱' in layer_calls
        assert 'R-柱' in layer_calls

    def test_creates_object_at_origin_and_moves_to_position(self) -> None:
        """柱はローカル原点に生成し、Move3D で絶対位置（XY + Z）へ移動する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        create_calls: list[tuple[str, float, float]] = []
        move3d_calls: list[tuple[float, float, float]] = []

        def capture_create(name: str, x: float, y: float, angle: float) -> object:
            create_calls.append((name, x, y))
            return object()

        def capture_move3d(x: float, y: float, z: float) -> None:
            move3d_calls.append((x, y, z))

        vs_mock.CreateCustomObject.side_effect = capture_create
        vs_mock.Move3D.side_effect = capture_move3d

        _run_execute_columns(vs_mock, [
            make_column_command(position=(500.0, 800.0), elevation=426.0),
        ])

        # ローカル原点 (0, 0) に生成
        assert create_calls == [('柱・間柱', 0, 0)]
        # Move3D で (500, 800, 426) へ移動
        assert any(
            abs(x - 500.0) < 1e-6 and abs(y - 800.0) < 1e-6 and abs(z - 426.0) < 1e-6
            for x, y, z in move3d_calls
        )

    def test_sets_record_fields(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(column_type='管柱', width=105.0, depth=120.0, height=2844.0),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        # (obj, plugin, field, value) のうち field→value の対応を取り出す
        fields = {field: value for _, _, field, value in set_rfield_args}
        assert fields['Type'] == '管柱'
        assert fields['SecShape'] == '矩形'
        assert fields['Width'] == '105'
        assert fields['Depth'] == '120'
        assert fields['Height'] == '2844'

    def test_enables_plan_symbol_on_plan_layer(self) -> None:
        """伏図記号を表示し、伏図レイヤを命令の plan_layer に設定する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(plan_layer='1-柱(伏図)'),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        fields = {field: value for _, _, field, value in set_rfield_args}
        assert fields['伏図記号を表示'] == 'True'
        assert fields['伏図レイヤ'] == '1-柱(伏図)'

    def test_sets_story_bounds_for_top_and_bottom(self) -> None:
        """上下端の高さをストーリレベル基準 (SetObjectStoryBound) でバインドする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(
                bottom_bound={'story': 0, 'level': '横架材天端', 'offset': 1.0},
                top_bound={'story': 1, 'level': '横架材天端', 'offset': -200.0},
            ),
        ])
        # SetObjectStoryBound(obj, boundID, boundType=2(Story), boundStory, level, offset)
        calls = [c.args for c in vs_mock.SetObjectStoryBound.call_args_list]
        # boundID→(boundType, boundStory, level, offset)
        by_id = {args[1]: args[2:] for args in calls}
        # 下端 (boundID=1): 当該階(0) の横架材天端, offset 1.0
        assert by_id[1] == (2, 0, '横架材天端', 1.0)
        # 上端 (boundID=0): 上階(1) の横架材天端, offset -200.0
        assert by_id[0] == (2, 1, '横架材天端', -200.0)

    def test_fallback_to_rect_when_plugin_unavailable(self) -> None:
        """柱・間柱プラグインが利用できない場合に断面の矩形にフォールバックする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        # プラグインが存在しない → Handle(0) を返す
        vs_mock.CreateCustomObject.return_value = vs_mock.Handle.return_value

        count = _run_execute_columns(vs_mock, [make_column_command()])

        # フォールバックでも 1 本描画される
        assert count == 1
        # SetRField は呼ばれない (フォールバック時)
        vs_mock.SetRField.assert_not_called()
        # 矩形が描画される
        vs_mock.Rect.assert_called_once()
