"""描画フェーズ (vw.column_mark) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import ColumnMarkCommand


def make_command() -> ColumnMarkCommand:
    return {
        'layer': '2-柱伏図記号',
        'class': '01作図-04記号-04構造-一般',
        'target_layer': '1to2-柱',
        'target_class': '',
        'size': 300.0,
        'style': '平面',
        'symbol': '柱伏図記号',
        'position': [0.0, 0.0],
    }


def _make_vs_mock(existing_layers: set[str]) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    # CreateCustomObjectN は生成した PIO ハンドル (非 NIL) を返す
    vs_mock.CreateCustomObjectN.return_value = 'PIO_HANDLE'
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.column_mark as vw_cm
        importlib.reload(vw_cm)
        return vw_cm


class TestExecuteColumnMarks:
    def test_places_pio_and_sets_parameters(self) -> None:
        vs_mock = _make_vs_mock({'2-柱伏図記号'})
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 1
        # アクティブレイヤを伏図記号レイヤに切り替えてから PIO を配置する
        vs_mock.Layer.assert_called_once_with('2-柱伏図記号')
        args = vs_mock.CreateCustomObjectN.call_args.args
        assert args[0] == '柱束伏図記号'
        assert args[1] == (0.0, 0.0)
        assert args[2] == 0
        # showPref=False で設定ダイアログを抑止する
        # (インポート中の手動入力を不要にするため)
        assert args[3] is False
        # PIO 本体 (記号) を命令の class (柱・束の伏図記号の作図クラス) に設定する
        vs_mock.SetClass.assert_called_once_with(
            'PIO_HANDLE', '01作図-04記号-04構造-一般')
        # 描画属性 (太さ・色・パターン・透明度等) をすべてクラス属性に従わせる
        vs_mock.SetPenColorByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetFillColorByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetLWByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetLSByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetFPatByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetMarkerByClass.assert_called_once_with('PIO_HANDLE')
        vs_mock.SetOpacityByClass.assert_called_once_with('PIO_HANDLE')
        # 検索対象レイヤ・クラス・記号サイズをパラメータに設定する
        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['TargetLayer'] == '1to2-柱'
        assert set_fields['TargetClass'] == ''
        assert set_fields['MarkSize'] == '300'
        # 記号スタイル(平面/断面)を MarkStyle パラメータに設定する
        assert set_fields['MarkStyle'] == '平面'
        # 伏図記号のシンボル(その span の種別のシンボル)を MarkSymbol に設定する
        assert set_fields['MarkSymbol'] == '柱伏図記号'
        # レコード名は PIO プラグイン名
        for c in vs_mock.SetRField.call_args_list:
            assert c.args[0] == 'PIO_HANDLE'
            assert c.args[1] == '柱束伏図記号'
        # 設定後にリセットして PIO の再描画 (柱検索→記号) を走らせる
        vs_mock.ResetObject.assert_called_once_with('PIO_HANDLE')

    def test_formats_integer_size_without_trailing_zero(self) -> None:
        vs_mock = _make_vs_mock({'2-柱伏図記号'})
        vw_cm = _load(vs_mock)

        command = make_command()
        command['size'] = 450.0
        vw_cm.execute_column_marks([command])

        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['MarkSize'] == '450'

    def test_creates_layer_when_missing(self) -> None:
        # 伏図記号レイヤ({to}-柱伏図記号)は story 命令が生成しないため、
        # 配置先レイヤが無ければ execute_column_marks が作成してから PIO を置く。
        vs_mock = _make_vs_mock(set())
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 1
        vs_mock.CreateLayer.assert_called_once_with('2-柱伏図記号', 1)
        vs_mock.Layer.assert_called_once_with('2-柱伏図記号')
        vs_mock.CreateCustomObjectN.assert_called_once()

    def test_skips_when_pio_cannot_be_created(self) -> None:
        # プラグイン未登録などで CreateCustomObjectN が NIL を返す場合は数えない
        vs_mock = _make_vs_mock({'2-柱伏図記号'})
        vs_mock.CreateCustomObjectN.return_value = vs_mock.Handle(0)
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 0
        vs_mock.ResetObject.assert_not_called()

    def test_passes_section_style(self) -> None:
        # 断面記号は柱レイヤ自身に配置し、MarkStyle=断面 を設定する
        vs_mock = _make_vs_mock({'1-柱'})
        vw_cm = _load(vs_mock)

        command = make_command()
        command['layer'] = '1-柱'
        command['class'] = '01作図-01線-02実線-01極細線'
        command['target_layer'] = '1-柱'
        command['style'] = '断面'
        count = vw_cm.execute_column_marks([command])

        assert count == 1
        vs_mock.SetClass.assert_called_once_with(
            'PIO_HANDLE', '01作図-01線-02実線-01極細線')
        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['TargetLayer'] == '1-柱'
        assert set_fields['MarkStyle'] == '断面'

    def test_passes_target_class_when_specified(self) -> None:
        vs_mock = _make_vs_mock({'2-柱伏図記号'})
        vw_cm = _load(vs_mock)

        command = make_command()
        command['target_class'] = '04構造-02木造-03柱-02管柱'
        vw_cm.execute_column_marks([command])

        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['TargetClass'] == '04構造-02木造-03柱-02管柱'


class TestPlanMarkLayers:
    def test_returns_distinct_plan_layers_in_order(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_cm = _load(vs_mock)

        section = make_command()
        section['layer'] = '1to2-柱'
        section['style'] = '断面'
        plan_a = make_command()  # layer '2-柱伏図記号'
        plan_b = make_command()
        plan_b['layer'] = '2.5-柱伏図記号'
        plan_a2 = make_command()  # 重複する平面レイヤ

        layers = vw_cm.plan_mark_layers([section, plan_a, plan_b, plan_a2])

        # 断面記号レイヤは含めず、平面記号レイヤを登場順・重複なしで返す
        assert layers == ['2-柱伏図記号', '2.5-柱伏図記号']
