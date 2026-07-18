"""描画フェーズ (vw.rebar) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import RebarCommand


def make_beam_command() -> RebarCommand:
    return {
        'layer': 'F-立上り', 'class': '04構造-01基礎-09鉄筋',
        'mode': 'beam', 'closed': False,
        'path': [[0.0, 0.0, 400.0], [3000.0, 0.0, 400.0]],
        'section_size': '120×500', 'top_bars': '1-D13',
        'bottom_bars': '1-D13', 'stirrup': 'D10@250',
        'main_bar': '', 'dist_bar': '', 'slab_thickness': 0.0,
    }


def make_slab_command() -> RebarCommand:
    return {
        'layer': 'F-底盤', 'class': '04構造-01基礎-09鉄筋',
        'mode': 'slab', 'closed': True,
        'path': [[0.0, 0.0, 50.0], [3000.0, 0.0, 50.0],
                 [3000.0, 2000.0, 50.0], [0.0, 2000.0, 50.0]],
        'section_size': '', 'top_bars': '', 'bottom_bars': '', 'stirrup': '',
        'main_bar': 'D13@150', 'dist_bar': 'D13@150', 'slab_thickness': 150.0,
    }


def _make_vs_mock(existing_layers: set[str]) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.LNewObj.return_value = 'PATH_HANDLE'
    # 既定は CreateCustomObjectN(showPref=False)で PIO を作る経路。生成した PIO
    # ハンドル(非 NIL)を返す。CreateCustomObjectPath はフォールバック用で既定は NIL。
    vs_mock.CreateCustomObjectN.return_value = 'PIO_HANDLE'
    vs_mock.CreateCustomObjectPath.return_value = null_handle
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.rebar as vw_rebar
        importlib.reload(vw_rebar)
        return vw_rebar


def _fields(vs_mock: MagicMock) -> dict[str, str]:
    return {c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list}


class TestExecuteRebars:
    def test_places_beam_pio_with_open_path_and_params(self) -> None:
        vs_mock = _make_vs_mock({'F-立上り'})
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars([make_beam_command()])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('F-立上り')
        # 梁モードは開いたパス
        vs_mock.OpenPoly.assert_called_once()
        vs_mock.ClosePoly.assert_not_called()
        # 3D パス頂点を平坦化して Poly3D に渡す
        assert vs_mock.Poly3D.call_args.args == (
            0.0, 0.0, 400.0, 3000.0, 0.0, 400.0)
        # 作成時ダイアログ抑止のため CreateCustomObjectN(showPref=False)で原点に作る
        create = vs_mock.CreateCustomObjectN.call_args.args
        assert create[0] == '鉄筋'
        assert create[1] == (0.0, 0.0)
        assert create[2] == 0.0
        assert create[3] is False
        # パスは SetCustomObjectPath で後付けする(CreateCustomObjectPath は使わない)
        vs_mock.SetCustomObjectPath.assert_called_once_with(
            'PIO_HANDLE', 'PATH_HANDLE')
        vs_mock.CreateCustomObjectPath.assert_not_called()
        # PIO 本体のクラスを命令の class に設定し描画属性をクラス属性に従わせる
        vs_mock.SetClass.assert_called_once_with('PIO_HANDLE', '04構造-01基礎-09鉄筋')
        vs_mock.SetPenColorByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetOpacityByClass.assert_called_once_with('PIO_HANDLE')
        # 梁モードのパラメータ
        fields = _fields(vs_mock)
        assert fields['Mode'] == '梁'
        assert fields['SectionSize'] == '120×500'
        assert fields['TopBars'] == '1-D13'
        assert fields['BottomBars'] == '1-D13'
        assert fields['Stirrup'] == 'D10@250'
        # スラブ用フィールドは設定しない
        assert 'MainBar' not in fields
        # レコード名は PIO プラグイン名
        for c in vs_mock.SetRField.call_args_list:
            assert c.args[0] == 'PIO_HANDLE'
            assert c.args[1] == '鉄筋'
        vs_mock.ResetObject.assert_called_once_with('PIO_HANDLE')

    def test_places_slab_pio_with_closed_path_and_params(self) -> None:
        vs_mock = _make_vs_mock({'F-底盤'})
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars([make_slab_command()])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('F-底盤')
        # スラブモードは閉じたパス
        vs_mock.ClosePoly.assert_called_once()
        vs_mock.OpenPoly.assert_not_called()
        assert vs_mock.Poly3D.call_args.args == (
            0.0, 0.0, 50.0, 3000.0, 0.0, 50.0,
            3000.0, 2000.0, 50.0, 0.0, 2000.0, 50.0)
        fields = _fields(vs_mock)
        assert fields['Mode'] == 'スラブ'
        assert fields['MainBar'] == 'D13@150'
        assert fields['DistBar'] == 'D13@150'
        # 整数のスラブ厚は末尾の .0 を付けない
        assert fields['SlabThickness'] == '150'
        # 梁用フィールドは設定しない
        assert 'SectionSize' not in fields

    def test_slab_path_z_is_layer_relative(self) -> None:
        # ストーリレベルにバインドされた F-底盤 レイヤは Z(標高)を持つ。3D パス図形は
        # レイヤ相対で座標を扱うため、絶対 Z のパスからレイヤ標高を引いてレイヤ相対 Z で
        # 与える(絶対 Z のままだとレイヤ標高ぶん浮き、配筋がコンクリート底盤の上に
        # 浮いて描画される)。底盤天端 Z=50 のレイヤでは path Z=50 → レイヤ相対 0。
        vs_mock = _make_vs_mock({'F-底盤'})
        vs_mock.GetZVals.return_value = (50.0, 0.0)
        vw_rebar = _load(vs_mock)

        vw_rebar.execute_rebars([make_slab_command()])

        # X・Y はそのまま、Z は 50(絶対) − 50(レイヤ標高) = 0(レイヤ相対)
        assert vs_mock.Poly3D.call_args.args == (
            0.0, 0.0, 0.0, 3000.0, 0.0, 0.0,
            3000.0, 2000.0, 0.0, 0.0, 2000.0, 0.0)

    def test_path_z_unchanged_when_layer_z_unavailable(self) -> None:
        # GetZVals がタプルを返さない環境(VW 2018 以前等)ではレイヤ標高 0 相当=補正なし。
        vs_mock = _make_vs_mock({'F-底盤'})
        vs_mock.GetZVals.return_value = None
        vw_rebar = _load(vs_mock)

        vw_rebar.execute_rebars([make_slab_command()])

        assert vs_mock.Poly3D.call_args.args == (
            0.0, 0.0, 50.0, 3000.0, 0.0, 50.0,
            3000.0, 2000.0, 50.0, 0.0, 2000.0, 50.0)

    def test_path_z_unchanged_when_getzvals_missing(self) -> None:
        # GetZVals 自体が無い環境(VW 2018 以前)は AttributeError を捕捉してレイヤ Z=0
        # 相当(補正なし)にフォールバックする。
        vs_mock = _make_vs_mock({'F-底盤'})
        vs_mock.GetZVals.side_effect = AttributeError
        vw_rebar = _load(vs_mock)

        vw_rebar.execute_rebars([make_slab_command()])

        assert vs_mock.Poly3D.call_args.args == (
            0.0, 0.0, 50.0, 3000.0, 0.0, 50.0,
            3000.0, 2000.0, 50.0, 0.0, 2000.0, 50.0)

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars([make_beam_command()])

        assert count == 0
        vs_mock.CreateCustomObjectN.assert_not_called()
        vs_mock.CreateCustomObjectPath.assert_not_called()

    def test_falls_back_to_create_path_when_n_returns_nil(self) -> None:
        # CreateCustomObjectN が NIL の場合は CreateCustomObjectPath で配置する
        vs_mock = _make_vs_mock({'F-立上り'})
        vs_mock.CreateCustomObjectN.return_value = vs_mock.Handle(0)
        vs_mock.CreateCustomObjectPath.return_value = 'PIO_HANDLE'
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars([make_beam_command()])

        assert count == 1
        # フォールバックはパス付きで直接作成する(SetCustomObjectPath は使わない)
        create = vs_mock.CreateCustomObjectPath.call_args.args
        assert create[0] == '鉄筋'
        assert create[1] == 'PATH_HANDLE'
        vs_mock.SetCustomObjectPath.assert_not_called()
        vs_mock.ResetObject.assert_called_once_with('PIO_HANDLE')

    def test_skips_when_pio_cannot_be_created(self) -> None:
        # CreateCustomObjectN も CreateCustomObjectPath も NIL の場合は数えない
        vs_mock = _make_vs_mock({'F-立上り'})
        vs_mock.CreateCustomObjectN.return_value = vs_mock.Handle(0)
        vs_mock.CreateCustomObjectPath.return_value = vs_mock.Handle(0)
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars([make_beam_command()])

        assert count == 0
        vs_mock.ResetObject.assert_not_called()

    def test_counts_multiple_and_switches_layers(self) -> None:
        vs_mock = _make_vs_mock({'F-立上り', 'F-底盤'})
        vw_rebar = _load(vs_mock)

        count = vw_rebar.execute_rebars(
            [make_beam_command(), make_slab_command()])

        assert count == 2
        layers = [c.args[0] for c in vs_mock.Layer.call_args_list]
        assert layers == ['F-立上り', 'F-底盤']
