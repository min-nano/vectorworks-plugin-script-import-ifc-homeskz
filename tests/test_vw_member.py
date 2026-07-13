"""描画フェーズ (vw.member) のテスト。vs をモックし手書きの member 命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Collection
from unittest.mock import MagicMock, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import MemberCommand


def make_member_command(layer: str = '1-横架材天端', member_id: str = '120×180 - 杉',
                        start: tuple[float, float] = (0.0, 0.0),
                        end: tuple[float, float] = (3000.0, 0.0),
                        width: float = 120.0, height: float = 180.0,
                        elevation: float = 473.0,
                        end_elevation: float | None = None,
                        level: str = '横架材天端',
                        member_class: str = '04構造-02木造-01土台-01土台',
                        ) -> MemberCommand:
    end_elev = elevation if end_elevation is None else end_elevation
    return {
        'layer': layer,
        'member_id': member_id,
        'class': member_class,
        'start': list(start),
        'end': list(end),
        'width': width,
        'height': height,
        'elevation': elevation,
        'end_elevation': end_elev,
        'start_bound': {'story_offset': 0, 'level': level, 'offset': 0.0},
        'end_bound': {'story_offset': 0, 'level': level, 'offset': 0.0},
    }


def _make_vs_mock(existing_layers: Collection[str] = ()) -> MagicMock:
    """execute_members() 用 vs モック。

    existing_layers に含まれるレイヤ名は GetObject で非 null を返す。
    CreateCustomObjectPath は非 null を返し (プラグイン利用可能) 、
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


def _run_execute_members(vs_mock: MagicMock, commands: list[MemberCommand]) -> int:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.member as vw_member
        importlib.reload(vw_member)
        return vw_member.execute_members(commands)


class TestExecuteMembers:
    def test_empty_commands_return_zero(self) -> None:
        vs_mock = _make_vs_mock()
        count = _run_execute_members(vs_mock, [])
        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_returns_count_of_drawn_members(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        count = _run_execute_members(vs_mock, [
            make_member_command(start=(0.0, 0.0)),
            make_member_command(start=(0.0, 1000.0)),
        ])
        assert count == 2

    def test_skips_command_when_layer_missing(self) -> None:
        """配置先レイヤが未生成の命令はスキップする(勝手にレイヤを作らない)。"""
        vs_mock = _make_vs_mock(existing_layers=set())
        count = _run_execute_members(vs_mock, [make_member_command()])
        assert count == 0
        vs_mock.Layer.assert_not_called()
        vs_mock.CreateLayer.assert_not_called()

    def test_switches_to_command_layer(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端', '2-横架材天端'})
        _run_execute_members(vs_mock, [
            make_member_command(layer='1-横架材天端'),
            make_member_command(layer='2-横架材天端'),
        ])
        layer_calls = [c.args[0] for c in vs_mock.Layer.call_args_list]
        assert '1-横架材天端' in layer_calls
        assert '2-横架材天端' in layer_calls

    def test_draws_path_locally_and_moves_to_position(self) -> None:
        """パスはローカル原点から方向ベクトルで作り、Move3D で絶対位置へ移動する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
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

        _run_execute_members(vs_mock, [
            make_member_command(start=(500.0, 500.0), end=(1100.0, 500.0), elevation=473.0),
        ])

        # パスはローカル原点 (0, 0) から方向ベクトル (600, 0, 0) へ
        assert nurbs_calls == [(0, 0)]
        assert vertex_calls == [
            (pytest.approx(600.0), pytest.approx(0.0), pytest.approx(0.0)),
        ]
        # Move3D で始端 (500, 500, 473) へ移動
        assert any(
            abs(x - 500.0) < 1e-6 and abs(y - 500.0) < 1e-6 and abs(z - 473.0) < 1e-6
            for x, y, z in move3d_calls
        )

    def test_draws_sloped_member_with_planar_path(self) -> None:
        """傾斜梁(elevation ≠ end_elevation)でもパスは水平(Z 成分 0)にする。

        傾斜は始端/終端の高さバインド(start_bound/end_bound)だけで表す。
        パスにも Z 成分を持たせると構造材ツールの高さバインドが加算されて傾斜が
        二重になり終端が 2 倍の高さに描画されるため(柱の二重加算(#54)と同種)。
        """
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        vertex_calls: list[tuple[float, float, float]] = []
        move3d_calls: list[tuple[float, float, float]] = []

        def capture_vertex(h: object, x: float, y: float, z: float) -> None:
            vertex_calls.append((x, y, z))

        def capture_move3d(x: float, y: float, z: float) -> None:
            move3d_calls.append((x, y, z))

        vs_mock.AddVertex3D.side_effect = capture_vertex
        vs_mock.Move3D.side_effect = capture_move3d

        _run_execute_members(vs_mock, [
            make_member_command(start=(0.0, 0.0), end=(600.0, 600.0),
                                elevation=527.0, end_elevation=1327.0),
        ])

        # 方向ベクトルは平面投影 (600, 600, 0)(Z は 0。傾斜はバインドで表す)
        assert vertex_calls == [
            (pytest.approx(600.0), pytest.approx(600.0), pytest.approx(0.0)),
        ]
        # Move3D で始端天端 (0, 0, 527) へ移動
        assert any(
            abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z - 527.0) < 1e-6
            for x, y, z in move3d_calls
        )

    def test_binds_height_to_story_level(self) -> None:
        """始端/終端の高さ基準を SetObjectStoryBound でストーリレベルにバインドする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        bound_calls: list[tuple[object, ...]] = []

        def capture_bound(obj: object, index: int, bound_type: int,
                          story_offset: int, level: str, offset: float) -> None:
            bound_calls.append((index, bound_type, story_offset, level, offset))

        vs_mock.SetObjectStoryBound.side_effect = capture_bound

        _run_execute_members(vs_mock, [
            make_member_command(level='横架材天端'),
        ])

        # 始端 (index 0)・終端 (index 1) とも boundType=2 (Story)・横架材天端
        assert (0, 2, 0, '横架材天端', 0.0) in bound_calls
        assert (1, 2, 0, '横架材天端', 0.0) in bound_calls

    def test_binds_sloped_member_with_distinct_offsets(self) -> None:
        """傾斜梁は始端/終端で異なる offset を持つ命令をそのままバインドする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        bound_calls: list[tuple[object, ...]] = []

        def capture_bound(obj: object, index: int, bound_type: int,
                          story_offset: int, level: str, offset: float) -> None:
            bound_calls.append((index, offset))

        vs_mock.SetObjectStoryBound.side_effect = capture_bound

        command = make_member_command()
        command['start_bound'] = {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0}
        command['end_bound'] = {'story_offset': 0, 'level': '横架材天端', 'offset': 800.0}
        _run_execute_members(vs_mock, [command])

        assert (0, 0.0) in bound_calls
        assert (1, 800.0) in bound_calls

    def test_sets_member_id_record_field(self) -> None:
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        _run_execute_members(vs_mock, [
            make_member_command(member_id='120×180 - 杉対称異等級集成材E105-F355'),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        member_id_values = [v for _, _, _, v in set_rfield_args]
        assert '120×180 - 杉対称異等級集成材E105-F355' in member_id_values

    def test_sets_class(self) -> None:
        """構造種別クラスを SetClass で割り当てる。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        _run_execute_members(vs_mock, [
            make_member_command(member_class='04構造-02木造-04梁桁-03床梁'),
        ])
        class_args = [c.args[1] for c in vs_mock.SetClass.call_args_list]
        assert '04構造-02木造-04梁桁-03床梁' in class_args

    def test_applies_plugin_style(self) -> None:
        """横架材のプラグインスタイル(木質構造材_横架材)を適用する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        _run_execute_members(vs_mock, [make_member_command()])
        vs_mock.SetPluginStyle.assert_called_once_with(
            vs_mock.CreateCustomObjectPath.return_value, '木質構造材_横架材')

    def test_updates_styled_objects_after_placing(self) -> None:
        """全配置後に UpdateStyledObjects でスタイルの描画属性(テクスチャ等)を反映する。

        SetPluginStyle はスタイルの関連付けまでで描画属性を反映しないため、
        配置後に UpdateStyledObjects を呼ばないとテクスチャ等が反映されない(#56)。
        by-instance の個別フィールドを設定し終えた全配置後に 1 回だけ呼ぶ。
        """
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        _run_execute_members(vs_mock, [
            make_member_command(start=(0.0, 0.0)),
            make_member_command(start=(0.0, 1000.0)),
        ])
        # 2 部材配置しても UpdateStyledObjects はスタイル単位で 1 回
        vs_mock.UpdateStyledObjects.assert_called_once_with('木質構造材_横架材')
        # 個別フィールド(SetRField)を設定し終えた後に呼ぶ
        methods = [c[0] for c in vs_mock.mock_calls]
        last_setrfield = max(i for i, m in enumerate(methods) if m == 'SetRField')
        assert methods.index('UpdateStyledObjects') > last_setrfield

    def test_no_style_update_when_nothing_placed(self) -> None:
        """1 件も配置しなければ UpdateStyledObjects を呼ばない。"""
        vs_mock = _make_vs_mock(existing_layers=set())
        _run_execute_members(vs_mock, [make_member_command()])
        vs_mock.UpdateStyledObjects.assert_not_called()

    def test_fallback_to_line_when_plugin_unavailable(self) -> None:
        """構造材プラグインが利用できない場合に通常線にフォールバックする。"""
        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        # プラグインが存在しない → Handle(0) を返す
        vs_mock.CreateCustomObjectPath.return_value = vs_mock.Handle.return_value

        count = _run_execute_members(vs_mock, [
            make_member_command(member_class='04構造-02木造-04梁桁-03床梁'),
        ])

        # フォールバックでも 1 本描画される
        assert count == 1
        # SetRField は呼ばれない (フォールバック時)
        vs_mock.SetRField.assert_not_called()
        # フォールバックの直線にもクラスを割り当てる
        class_args = [c.args[1] for c in vs_mock.SetClass.call_args_list]
        assert '04構造-02木造-04梁桁-03床梁' in class_args
