"""描画フェーズ (vw.column) のテスト。vs をモックし手書きの column 命令で検証する。

柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描画される。
"""
from __future__ import annotations

import importlib
from typing import Collection
from unittest.mock import MagicMock, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    ColumnCommand,
    StoryBoundCommand,
)


def make_column_command(layer: str = '1-柱',
                        member_id: str = '105×105 - 管柱',
                        position: tuple[float, float] = (0.0, 0.0),
                        width: float = 105.0, depth: float = 105.0,
                        height: float = 2844.0, elevation: float = 426.0,
                        start_bound: StoryBoundCommand | None = None,
                        end_bound: StoryBoundCommand | None = None,
                        top_hardware: str = '',
                        bottom_hardware: str = '',
                        column_class: str = '04構造-02木造-03柱-02管柱',
                        ) -> ColumnCommand:
    if start_bound is None:
        start_bound = {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0}
    if end_bound is None:
        end_bound = {'story_offset': 1, 'level': '軒高', 'offset': 0.0}
    return {
        'layer': layer,
        'member_id': member_id,
        'class': column_class,
        'position': list(position),
        'width': width,
        'depth': depth,
        'height': height,
        'elevation': elevation,
        'start_bound': start_bound,
        'end_bound': end_bound,
        'top_hardware': top_hardware,
        'bottom_hardware': bottom_hardware,
    }


def _make_vs_mock(existing_layers: Collection[str] = ()) -> MagicMock:
    """execute_columns() 用 vs モック。

    existing_layers に含まれるレイヤ名は GetObject で非 null を返す。
    CreateCustomObjectPath は非 null を返し (プラグイン利用可能)、
    SetRField / ResetObject の呼び出しを追跡できる。
    """
    vs_mock = MagicMock()
    null_handle = object()
    non_null_handle = object()
    vs_mock.Handle.return_value = null_handle
    vs_mock.LNewObj.return_value = non_null_handle
    vs_mock.CreateCustomObjectPath.return_value = non_null_handle

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
        """配置先レイヤが未生成の命令はスキップする(勝手にレイヤを作らない)。"""
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

    def test_draws_vertical_path_and_moves_to_position(self) -> None:
        """鉛直パスをローカル原点から高さ分作り、Move3D で下端の絶対位置へ移動する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        nurbs_calls: list[tuple[float, float]] = []
        vertex_calls: list[tuple[float, float, float]] = []
        move3d_calls: list[tuple[float, float, float]] = []

        def capture_nurbs(x: float, y: float, z: float, closed: bool, order: int) -> object:
            nurbs_calls.append((x, y))
            return object()

        def capture_vertex(h: object, x: float, y: float, z: float) -> None:
            vertex_calls.append((x, y, z))

        def capture_move3d(x: float, y: float, z: float) -> None:
            move3d_calls.append((x, y, z))

        vs_mock.CreateNurbsCurve.side_effect = capture_nurbs
        vs_mock.AddVertex3D.side_effect = capture_vertex
        vs_mock.Move3D.side_effect = capture_move3d

        _run_execute_columns(vs_mock, [
            make_column_command(position=(500.0, 800.0), height=2844.0, elevation=426.0),
        ])

        # パスはローカル原点 (0, 0) から鉛直方向 (0, 0, 高さ) へ
        assert nurbs_calls == [(0, 0)]
        assert vertex_calls == [
            (pytest.approx(0.0), pytest.approx(0.0), pytest.approx(2844.0)),
        ]
        # Move3D で下端 (500, 800, 426) へ移動
        assert any(
            abs(x - 500.0) < 1e-6 and abs(y - 800.0) < 1e-6 and abs(z - 426.0) < 1e-6
            for x, y, z in move3d_calls
        )

    def test_sets_structural_member_record_fields(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(member_id='105×120 - 管柱', width=105.0, depth=120.0),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        # (obj, plugin, field, value) のうち plugin と field→value を取り出す
        plugins = {plugin for _, plugin, _, _ in set_rfield_args}
        fields = {field: value for _, _, field, value in set_rfield_args}
        assert plugins == {'StructuralMember'}
        assert fields['MemberID'] == '105×120 - 管柱'
        assert fields['ProfileShape'] == 'Rectangle'
        assert fields['MajorBreadth'] == '105'
        assert fields['MajorDepth'] == '120'
        assert fields['B'] == '105'
        assert fields['D'] == '120'
        # 配置基準は中央(4)。上部中央(1)にすると柱の断面が軸から上方向にずれる
        assert fields['AxisAlign'] == '4'
        # 構造用途は柱(4)
        assert fields['StructuralUse'] == '4'

    def test_binds_height_to_story_levels(self) -> None:
        """始端・終端の高さ基準を SetObjectStoryBound でストーリレベルにバインドする。"""
        vs_mock = _make_vs_mock(existing_layers={'2-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(
                layer='2-柱',
                start_bound={'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
                end_bound={'story_offset': 1, 'level': '軒高', 'offset': 0.0}),
        ])
        bound_calls = [c.args for c in vs_mock.SetObjectStoryBound.call_args_list]
        # (handle, end, mode, story_offset, level, offset)
        starts = [c for c in bound_calls if c[1] == 0]
        ends = [c for c in bound_calls if c[1] == 1]
        assert len(starts) == 1
        assert len(ends) == 1
        assert starts[0][3:] == (0, '横架材天端', 0.0)
        assert ends[0][3:] == (1, '軒高', 0.0)

    def test_top_story_binds_both_ends_to_eaves(self) -> None:
        """最上階の柱は始端・終端とも軒高基準で、終端は柱高さ分のオフセットを持つ。"""
        vs_mock = _make_vs_mock(existing_layers={'R-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(
                layer='R-柱', height=900.0,
                start_bound={'story_offset': 0, 'level': '軒高', 'offset': 0.0},
                end_bound={'story_offset': 0, 'level': '軒高', 'offset': 900.0}),
        ])
        bound_calls = [c.args for c in vs_mock.SetObjectStoryBound.call_args_list]
        starts = [c for c in bound_calls if c[1] == 0]
        ends = [c for c in bound_calls if c[1] == 1]
        assert starts[0][3:] == (0, '軒高', 0.0)
        assert ends[0][3:] == (0, '軒高', 900.0)

    def test_member_id_carries_hardware_spec(self) -> None:
        """柱頭・柱脚金物の仕様は member_id 経由で MemberID に格納される。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(
                member_id='105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)',
                top_hardware='柱頭金物:(ろ)', bottom_hardware='柱脚金物:(い)'),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        fields = {field: value for _, _, field, value in set_rfield_args}
        assert fields['MemberID'] == '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'

    def test_profile_polygon_is_centered_on_axis(self) -> None:
        """断面プロファイルの矩形がパス軸(原点)を中心とした座標で定義される。

        IFC 配置座標は断面中心なので、プロファイル多角形も原点中心 (-w/2, -d/2)〜
        (w/2, d/2) とすることでパス軸が断面の上下左右中心を通るようにする。
        """
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        poly_calls: list[tuple[float, ...]] = []

        def capture_poly(*args: float) -> None:
            poly_calls.append(args)

        vs_mock.Poly.side_effect = capture_poly

        _run_execute_columns(vs_mock, [
            make_column_command(width=105.0, depth=120.0),
        ])

        assert len(poly_calls) == 1
        coords = poly_calls[0]
        # 4頂点 (x1,y1, x2,y2, x3,y3, x4,y4) の X 座標は ±w/2、Y 座標は ±d/2
        xs = [coords[i] for i in range(0, 8, 2)]
        ys = [coords[i] for i in range(1, 8, 2)]
        assert pytest.approx(min(xs)) == -105 / 2
        assert pytest.approx(max(xs)) == 105 / 2
        assert pytest.approx(min(ys)) == -120 / 2
        assert pytest.approx(max(ys)) == 120 / 2

    def test_sets_class(self) -> None:
        """柱種別クラスを SetClass で割り当てる。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(column_class='04構造-02木造-03柱-01通し柱'),
        ])
        class_args = [c.args[1] for c in vs_mock.SetClass.call_args_list]
        assert '04構造-02木造-03柱-01通し柱' in class_args

    def test_fallback_to_rect_when_plugin_unavailable(self) -> None:
        """構造材プラグインが利用できない場合に断面の矩形にフォールバックする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        # プラグインが存在しない → Handle(0) を返す
        vs_mock.CreateCustomObjectPath.return_value = vs_mock.Handle.return_value

        count = _run_execute_columns(vs_mock, [
            make_column_command(column_class='04構造-02木造-05小屋組-02小屋束'),
        ])

        # フォールバックでも 1 本描画される
        assert count == 1
        # SetRField は呼ばれない (フォールバック時)
        vs_mock.SetRField.assert_not_called()
        # 矩形が描画される
        vs_mock.Rect.assert_called_once()
        # フォールバックの矩形にもクラスを割り当てる
        class_args = [c.args[1] for c in vs_mock.SetClass.call_args_list]
        assert '04構造-02木造-05小屋組-02小屋束' in class_args
