"""描画フェーズ (vw.footing) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import (
    SlabCommand,
    WallCommand,
    WallJoinCommand,
)


def make_wall_command() -> WallCommand:
    return {
        'layer': 'F-立上り', 'class': '04構造-01基礎-03立ち上がり',
        'start': [0.0, 0.0], 'end': [3000.0, 0.0], 'thickness': 120.0,
        'bottom_bound': {'story_offset': 0, 'level': 'GL', 'offset': -100.0},
        'top_bound': {'story_offset': 1, 'level': '横架材天端', 'offset': -190.0},
    }


def make_wall_join_command() -> WallJoinCommand:
    return {'a': 0, 'b': 1, 'point': [0.0, 0.0], 'join_type': 2, 'capped': False}


def make_slab_command() -> SlabCommand:
    return {
        'layer': 'F-底盤', 'class': '04構造-01基礎-02基礎スラブ',
        'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0], [0.0, 2000.0]],
        'elevation': 50.0,
        'bound': {'story_offset': 0, 'level': '底盤天端', 'offset': 0.0},
    }


def _make_vs_mock(existing_layers: set[str]) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.LNewObj.return_value = object()
    vs_mock.CreateSlab.return_value = object()
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.footing as vw_footing
        importlib.reload(vw_footing)
        return vw_footing


class TestExecuteWalls:
    def test_draws_wall_with_thickness_and_bounds(self) -> None:
        vs_mock = _make_vs_mock({'F-立上り'})
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_walls([make_wall_command()])

        assert count == 1
        vs_mock.DoubLines.assert_called_once_with(120.0)
        wall_args = vs_mock.Wall.call_args.args
        assert wall_args == (0.0, 0.0, 3000.0, 0.0)
        vs_mock.SetClass.assert_called_once()
        # 壁スタイル(基礎 - 木造ベタ基礎150mm)を壁芯に揃えて適用する
        style_args = vs_mock.SetWallStyle.call_args.args
        assert style_args[1:] == ('基礎 - 木造ベタ基礎150mm', 0.0, 0.0)
        # 壁専用の SetWallOverallHeights で下端=GL(自階=0)、上端=横架材天端
        # (上階=1)を Story(boundType=2)にバインドする。汎用の
        # SetObjectStoryBound は壁では効かない(レイヤ壁高さに従ってしまう)ため
        # 使わない。
        vs_mock.SetObjectStoryBound.assert_not_called()
        args = vs_mock.SetWallOverallHeights.call_args.args
        # (obj, botType, botStory, botLevel, botOffset, topType, topStory,
        #  topLevel, topOffset)
        assert args[1:] == (2, 0, 'GL', -100.0, 2, 1, '横架材天端', -190.0)

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_walls([make_wall_command()])

        assert count == 0
        vs_mock.Wall.assert_not_called()

    def test_fallback_to_line_when_wall_not_created(self) -> None:
        vs_mock = _make_vs_mock({'F-立上り'})
        # Wall を作っても LNewObj が NIL を返す(壁が作れなかった)
        vs_mock.LNewObj.return_value = vs_mock.Handle(0)
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_walls([make_wall_command()])

        assert count == 1
        vs_mock.MoveTo.assert_called_once()
        vs_mock.LineTo.assert_called_once()


class TestExecuteWallJoins:
    def test_records_wall_handles_by_index(self) -> None:
        vs_mock = _make_vs_mock({'F-立上り'})
        # 各 draw_wall で異なる壁ハンドルを返させる (LNewObj は draw_wall で 1 回)
        vs_mock.LNewObj.side_effect = ['WALL_0', 'WALL_1']
        vw_footing = _load(vs_mock)

        handles: dict[int, Any] = {}
        count = vw_footing.execute_walls(
            [make_wall_command(), make_wall_command()], handles)

        assert count == 2
        assert handles == {0: 'WALL_0', 1: 'WALL_1'}

    def test_joins_walls_via_join_walls(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_footing = _load(vs_mock)

        handles = {0: 'WALL_A', 1: 'WALL_B'}
        count = vw_footing.execute_wall_joins([make_wall_join_command()], handles)

        assert count == 1
        # (firstWall, secondWall, pt_a, pt_b, joinModifier, capped, showAlerts)
        args = vs_mock.JoinWalls.call_args.args
        assert args[0] == 'WALL_A'
        assert args[1] == 'WALL_B'
        assert args[2] == (0.0, 0.0)
        assert args[3] == (0.0, 0.0)
        assert args[4] == 2       # join_type (L)
        assert args[5] is False   # capped(同じ天端高さ=コンクリート一体で閉じない)
        assert args[6] is False   # showAlerts

    def test_passes_capped_true_for_height_difference(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_footing = _load(vs_mock)

        command = make_wall_join_command()
        command['capped'] = True
        handles = {0: 'WALL_A', 1: 'WALL_B'}
        count = vw_footing.execute_wall_joins([command], handles)

        assert count == 1
        # 天端高さの異なる立上りは capped=True で結合する
        assert vs_mock.JoinWalls.call_args.args[5] is True

    def test_skips_when_handle_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_footing = _load(vs_mock)

        # b(index 1)のハンドルが記録されていない(壁未配置)
        handles = {0: 'WALL_A'}
        count = vw_footing.execute_wall_joins([make_wall_join_command()], handles)

        assert count == 0
        vs_mock.JoinWalls.assert_not_called()


class TestExecuteSlabs:
    def test_draws_slab_via_create_slab(self) -> None:
        vs_mock = _make_vs_mock({'F-底盤'})
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_slabs([make_slab_command()])

        assert count == 1
        # 外形ポリゴンを作って CreateSlab に渡す
        vs_mock.BeginPoly.assert_called_once()
        vs_mock.EndPoly.assert_called_once()
        vs_mock.CreateSlab.assert_called_once()
        # SetSlabHeight にはスラブ厚ではなく天端の絶対 Z (elevation) を渡す
        vs_mock.SetSlabHeight.assert_called_once_with(
            vs_mock.CreateSlab.return_value, 50.0)
        # 天端を底盤天端にバインド
        bound_calls = [c.args for c in vs_mock.SetObjectStoryBound.call_args_list]
        assert any(a[1] == 0 and a[4] == '底盤天端' for a in bound_calls)
        # 外形の頂点数分 LineTo (始点は MoveTo)
        assert vs_mock.MoveTo.call_count == 1
        assert vs_mock.LineTo.call_count == 3

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_slabs([make_slab_command()])

        assert count == 0
        vs_mock.CreateSlab.assert_not_called()

    def test_fallback_to_polygon_when_slab_not_created(self) -> None:
        vs_mock = _make_vs_mock({'F-底盤'})
        vs_mock.CreateSlab.return_value = vs_mock.Handle(0)
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_slabs([make_slab_command()])

        assert count == 1
        vs_mock.SetSlabHeight.assert_not_called()
        # フォールバックでポリゴンにクラスを設定
        vs_mock.SetClass.assert_called_once()
