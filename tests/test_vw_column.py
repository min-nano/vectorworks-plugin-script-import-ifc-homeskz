"""描画フェーズ (vw.column) のテスト。vs をモックし手書きの column 命令で検証する。

柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描画される。
"""
from __future__ import annotations

import importlib
from typing import Collection
from unittest.mock import MagicMock, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import ColumnCommand


def make_column_command(layer: str = '1-柱',
                        member_id: str = '105×105 - 管柱',
                        position: tuple[float, float] = (0.0, 0.0),
                        width: float = 105.0, depth: float = 105.0,
                        height: float = 2844.0, elevation: float = 426.0,
                        top_hardware: str = '',
                        bottom_hardware: str = '',
                        column_class: str = '04構造-02木造-03柱-02管柱',
                        structural_use: str = '4',
                        ) -> ColumnCommand:
    return {
        'layer': layer,
        'member_id': member_id,
        'class': column_class,
        'structural_use': structural_use,
        'position': list(position),
        'width': width,
        'depth': depth,
        'height': height,
        'elevation': elevation,
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
        # 構造用途は命令の structural_use(既定は柱="4")
        assert fields['StructuralUse'] == '4'

    def test_structural_use_comes_from_command(self) -> None:
        """構造用途 (StructuralUse) は命令の structural_use をそのまま設定する。

        小屋束は "5"(小屋束用途)。柱用途 ("4") のままだと VW の柱高さモデルで
        上端の高さオフセットと部材長が矛盾し上端高さが崩れる。
        """
        vs_mock = _make_vs_mock(existing_layers={'R-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(
                layer='R-柱', member_id='90×105 - 小屋束',
                column_class='04構造-02木造-05小屋組-02小屋束',
                structural_use='5'),
        ])
        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        fields = {field: value for _, _, field, value in set_rfield_args}
        assert fields['StructuralUse'] == '5'

    def test_does_not_bind_height_to_story_levels(self) -> None:
        """柱は高さをパスのジオメトリで決めるため SetObjectStoryBound を呼ばない。

        鉛直材ではバインドの高さがパス由来の部材長に加算され上端が二重になるため
        (梁は水平方向の部材長なので加算にならず、bound を使う)。
        """
        vs_mock = _make_vs_mock(existing_layers={'2-柱'})
        _run_execute_columns(vs_mock, [make_column_command(layer='2-柱')])
        vs_mock.SetObjectStoryBound.assert_not_called()

    def test_top_of_column_is_path_geometry(self) -> None:
        """柱の上端はパス(下端 Z + 高さ)で決まる。Move3D で下端の絶対 Z に配置し、
        パスは高さ分の鉛直ベクトル。バインドで二重に持ち上げない。"""
        vs_mock = _make_vs_mock(existing_layers={'R-柱'})
        vertex_calls: list[tuple[float, float, float]] = []
        move3d_calls: list[tuple[float, float, float]] = []
        vs_mock.AddVertex3D.side_effect = (
            lambda h, x, y, z: vertex_calls.append((x, y, z)))
        vs_mock.Move3D.side_effect = (
            lambda x, y, z: move3d_calls.append((x, y, z)))

        _run_execute_columns(vs_mock, [
            make_column_command(layer='R-柱', height=900.0, elevation=6300.0),
        ])
        # パスは (0,0,高さ) の鉛直ベクトル、下端の絶対 Z(6300)へ Move3D
        assert vertex_calls == [(0, 0, 900)]
        assert any(abs(z - 6300.0) < 1e-6 for _, _, z in move3d_calls)
        vs_mock.SetObjectStoryBound.assert_not_called()

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

    def test_applies_plugin_style(self) -> None:
        """柱・小屋束のプラグインスタイル(木質構造材_柱・束)を適用する。"""
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [make_column_command()])
        vs_mock.SetPluginStyle.assert_called_once_with(
            vs_mock.CreateCustomObjectPath.return_value, '木質構造材_柱・束')

    def test_updates_styled_objects_after_placing(self) -> None:
        """全配置後に UpdateStyledObjects でスタイルの描画属性(テクスチャ等)を反映する。

        SetPluginStyle はスタイルの関連付けまでで描画属性を反映しないため、
        配置後に UpdateStyledObjects を呼ばないとテクスチャ等が反映されない(#56)。
        by-instance の個別フィールドを設定し終えた全配置後に 1 回だけ呼ぶ。
        """
        vs_mock = _make_vs_mock(existing_layers={'1-柱'})
        _run_execute_columns(vs_mock, [
            make_column_command(position=(0.0, 0.0)),
            make_column_command(position=(1000.0, 0.0)),
        ])
        # 2 本配置しても UpdateStyledObjects はスタイル単位で 1 回
        vs_mock.UpdateStyledObjects.assert_called_once_with('木質構造材_柱・束')
        # 個別フィールド(SetRField)を設定し終えた後に呼ぶ
        methods = [c[0] for c in vs_mock.mock_calls]
        last_setrfield = max(i for i, m in enumerate(methods) if m == 'SetRField')
        assert methods.index('UpdateStyledObjects') > last_setrfield

    def test_no_style_update_when_nothing_placed(self) -> None:
        """1 件も配置しなければ UpdateStyledObjects を呼ばない。"""
        vs_mock = _make_vs_mock(existing_layers=set())
        _run_execute_columns(vs_mock, [make_column_command()])
        vs_mock.UpdateStyledObjects.assert_not_called()

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
