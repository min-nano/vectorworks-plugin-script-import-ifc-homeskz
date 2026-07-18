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
    return {'a': 0, 'b': 1, 'point': [0.0, 0.0],
            'pick_a': [30.0, 0.0], 'pick_b': [0.0, 30.0],
            'join_type': 2, 'capped': False}


def make_slab_command() -> SlabCommand:
    return {
        'layer': 'F-底盤', 'class': '04構造-01基礎-02基礎スラブ',
        'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0], [0.0, 2000.0]],
        'elevation': 50.0, 'thickness': 150.0,
        'bound': {'story_offset': 0, 'level': '底盤天端', 'offset': 0.0},
        'modifiers': [],
    }


def make_slab_with_modifier() -> SlabCommand:
    command = make_slab_command()
    command['modifiers'] = [{
        'profile': [[0.0, 0.0], [-150.0, 0.0], [-290.0, 140.0], [0.0, 140.0]],
        'depth': 1060.0,
        'origin': [760.0, 5520.0, -240.0],
        'azimuth': 0.0,
    }]
    return command


# 既定の基礎スラブスタイル名(コンクリート 150mm)
BASE_SLAB_STYLE = '基礎スラブ - コンクリート 150mm / 捨てコン 30mm / 砕石 100mm'


def _make_vs_mock(existing_layers: set[str]) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.LNewObj.return_value = object()
    vs_mock.CreateSlab.return_value = object()
    # 既定ではスラブスタイルが 1 件も無い(styling を発火させない)
    vs_mock.BuildResourceList.return_value = (0, 0)
    return vs_mock


def _style_handle(name: str) -> str:
    """スタイル名に対応するテスト用ハンドル文字列。"""
    return 'STYLE_H_' + name


def _make_style_vs_mock(
    styles: set[str], existing_layers: set[str] | None = None,
) -> MagicMock:
    """スラブスタイルの解決を検証するための vs モック。

    ``styles`` は現在ドキュメントに存在するスラブスタイル名の集合。
    ``BuildResourceList`` / ``GetNameFromResourceList`` / ``GetResourceFromList``
    でこの一覧と各スタイルのハンドルを返す(``GetObject`` はレイヤの存在確認だけに
    使い、スタイルには使わない)。``GetParent`` は親コンテナを返す。
    """
    if existing_layers is None:
        existing_layers = {'F-底盤'}
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    style_list = sorted(styles)
    vs_mock.BuildResourceList.return_value = (999, len(style_list))

    def name_from_list(list_id: int, index: int) -> str:
        return style_list[index - 1]  # 1-based

    def resource_from_list(list_id: int, index: int) -> str:
        return _style_handle(style_list[index - 1])

    vs_mock.GetNameFromResourceList.side_effect = name_from_list
    vs_mock.GetResourceFromList.side_effect = resource_from_list
    vs_mock.GetParent.return_value = 'PARENT'

    def get_obj(name: str) -> object:
        # レイヤの存在確認用。スタイルの取得には使わない。
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.LNewObj.return_value = object()
    vs_mock.CreateSlab.return_value = 'SLAB'
    vs_mock.CreateDuplicateObject.return_value = 'DUP'
    vs_mock.Name2Index.return_value = 42
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
        # ピック点は各壁の残す側に寄せた pick_a / pick_b を渡す(交点そのものでは
        # 残す側が曖昧で VW が L 結合でコーナーを詰めないため)
        assert args[2] == (30.0, 0.0)
        assert args[3] == (0.0, 30.0)
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


class TestExecuteSlabsWithModifiers:
    def test_carves_slab_and_draws_beam_solid(self) -> None:
        # 地中梁を持つ底盤は、台形プリズムを 2 回作る: (1) 削り取りモディファイアとして
        # CreateSlab の通常スラブに SetCustomObjectProfileGroup で渡し底盤を削り取る、
        # (2) 同じ台形プリズムを独立した可視ソリッドとして基礎スラブクラスで置く。
        vs_mock = _make_vs_mock({'F-底盤'})
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_slabs([make_slab_with_modifier()])

        assert count == 1
        # 底盤は通常の CreateSlab(可視・スタイル付き)で作る。PIO 直接作成・ModifySlab は不使用。
        vs_mock.CreateSlab.assert_called_once()
        vs_mock.CreateCustomObjectN.assert_not_called()
        vs_mock.CreateCustomObjectPath.assert_not_called()
        vs_mock.ModifySlab.assert_not_called()
        slab = vs_mock.CreateSlab.return_value
        # (1) 削り取りモディファイア群を通常スラブのプロファイル群として渡す(clip)
        vs_mock.SetCustomObjectProfileGroup.assert_called_once()
        assert vs_mock.SetCustomObjectProfileGroup.call_args.args[0] is slab
        vs_mock.BeginGroup.assert_called_once()
        vs_mock.EndGroup.assert_called_once()
        # 台形プリズムは 2 回作る(削り取り 1 + 可視ソリッド 1)
        assert vs_mock.BeginXtrd.call_count == 2
        assert vs_mock.EndXtrd.call_count == 2
        # 各ソリッドに 1160=False を立てる(レイヤ平面のワールド 3D)
        bool_calls = [c.args for c in vs_mock.SetObjectVariableBoolean.call_args_list]
        assert any(a[1] == 1160 and a[2] is False for a in bool_calls)
        # (2) 可視の地中梁ソリッドに底盤と同じ基礎スラブクラスを付ける
        class_calls = [c.args for c in vs_mock.SetClass.call_args_list]
        assert any(a[1] == '04構造-01基礎-02基礎スラブ'
                   and a[0] is vs_mock.LNewObj.return_value for a in class_calls)
        # 可視の地中梁ソリッドに「断面ビューポートで構造用図形として扱う」
        # (Mark Object as Structural=selector 702)を立てる
        assert any(a[1] == 702 and a[2] is True for a in bool_calls)
        # Z は絶対値(梁下端のワールド Z)そのまま。断面天端は実形状のまま(v=140)。
        move_calls = [c.args for c in vs_mock.Move3D.call_args_list]
        assert (760.0, 5520.0, -240.0) in move_calls
        line_calls = [c.args for c in vs_mock.LineTo.call_args_list]
        assert (-290.0, 140.0) in line_calls
        # スラブとして天端・バインド・スタイル対象は従来どおり
        vs_mock.SetSlabHeight.assert_called_once_with(slab, 50.0)

    def test_draws_beam_solid_even_when_slab_not_created(self) -> None:
        # スラブが作れなくても(フォールバック)、地中梁の可視ソリッドは描く。
        vs_mock = _make_vs_mock({'F-底盤'})
        vs_mock.CreateSlab.return_value = vs_mock.Handle(0)
        vw_footing = _load(vs_mock)

        count = vw_footing.execute_slabs([make_slab_with_modifier()])

        assert count == 1
        # 削り取りは行われないが、可視の地中梁ソリッドは 1 本描く
        vs_mock.SetCustomObjectProfileGroup.assert_not_called()
        assert vs_mock.BeginXtrd.call_count == 1
        class_calls = [c.args for c in vs_mock.SetClass.call_args_list]
        assert any(a[1] == '04構造-01基礎-02基礎スラブ' for a in class_calls)

    def test_slab_without_modifiers_uses_create_slab(self) -> None:
        vs_mock = _make_vs_mock({'F-底盤'})
        vw_footing = _load(vs_mock)

        vw_footing.execute_slabs([make_slab_command()])

        vs_mock.CreateSlab.assert_called_once()
        vs_mock.CreateCustomObjectPath.assert_not_called()
        vs_mock.CreateCustomObjectN.assert_not_called()
        vs_mock.ModifySlab.assert_not_called()
        vs_mock.SetCustomObjectProfileGroup.assert_not_called()
        vs_mock.BeginXtrd.assert_not_called()


class TestSlabStyles:
    def test_applies_existing_style_for_default_thickness(self) -> None:
        # 150mm 底盤は既存の既定スタイルをそのまま適用する(複製しない)
        vs_mock = _make_style_vs_mock({BASE_SLAB_STYLE})
        vw_footing = _load(vs_mock)

        vw_footing.execute_slabs([make_slab_command()])

        vs_mock.CreateDuplicateObject.assert_not_called()
        # ref 番号は正の Name2Index(スタイル名)(VW でスラブスタイルは正値のみ適用)
        vs_mock.SetSlabStyle.assert_called_once_with('SLAB', 42)

    def test_creates_style_for_non_default_thickness(self) -> None:
        # 180mm は既定スタイルを複製し、コンクリート厚(#1)を 180 にして適用する
        vs_mock = _make_style_vs_mock({BASE_SLAB_STYLE})
        vw_footing = _load(vs_mock)

        command = make_slab_command()
        command['thickness'] = 180.0
        vw_footing.execute_slabs([command])

        # 複製元は列挙で得た既定スタイルのハンドル、挿入先は親コンテナ(GetParent)
        vs_mock.CreateDuplicateObject.assert_called_once_with(
            _style_handle(BASE_SLAB_STYLE), 'PARENT')
        target = '基礎スラブ - コンクリート 180mm / 捨てコン 30mm / 砕石 100mm'
        vs_mock.SetName.assert_called_once_with('DUP', target)
        # 最上層(#1)= コンクリートの厚みを 180 に設定
        vs_mock.SetComponentWidth.assert_called_once_with('DUP', 1, 180.0)
        vs_mock.SetSlabStyle.assert_called_once_with('SLAB', 42)

    def test_finds_base_style_regardless_of_blinding_gravel_thickness(self) -> None:
        # 捨てコン・砕石の厚みが既定と違っても既定スタイルを見つけ、派生名にも引き継ぐ
        base = '基礎スラブ - コンクリート 150mm / 捨てコン 50mm / 砕石 120mm'
        vs_mock = _make_style_vs_mock({base})
        vw_footing = _load(vs_mock)

        command = make_slab_command()
        command['thickness'] = 200.0
        vw_footing.execute_slabs([command])

        target = '基礎スラブ - コンクリート 200mm / 捨てコン 50mm / 砕石 120mm'
        vs_mock.SetName.assert_called_once_with('DUP', target)

    def test_skips_style_when_thickness_none(self) -> None:
        # thickness=None(地中梁など)はスタイルを適用せず、リソース列挙もしない
        vs_mock = _make_style_vs_mock({BASE_SLAB_STYLE})
        vw_footing = _load(vs_mock)

        command = make_slab_command()
        command['thickness'] = None
        vw_footing.execute_slabs([command])

        vs_mock.BuildResourceList.assert_not_called()
        vs_mock.SetSlabStyle.assert_not_called()

    def test_skips_style_when_base_style_missing(self) -> None:
        # 既定スタイルが無ければ複製元が無いためスタイルを付けない
        vs_mock = _make_style_vs_mock(set())
        vw_footing = _load(vs_mock)

        vw_footing.execute_slabs([make_slab_command()])

        vs_mock.CreateDuplicateObject.assert_not_called()
        vs_mock.SetSlabStyle.assert_not_called()

    def test_caches_style_ref_across_slabs(self) -> None:
        # 同一厚みの底盤が複数あっても複製は 1 回、適用は各スラブに行う
        vs_mock = _make_style_vs_mock({BASE_SLAB_STYLE})
        vw_footing = _load(vs_mock)

        c1 = make_slab_command()
        c1['thickness'] = 180.0
        c2 = make_slab_command()
        c2['thickness'] = 180.0
        vw_footing.execute_slabs([c1, c2])

        vs_mock.CreateDuplicateObject.assert_called_once()
        assert vs_mock.SetSlabStyle.call_count == 2
