"""描画フェーズ (vw.column_mark) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import ColumnMarkCommand


def make_command() -> ColumnMarkCommand:
    return {
        'layer': '2-下階柱',
        'target_layer': '1-柱',
        'target_class': '',
        'size': 300.0,
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
        vs_mock = _make_vs_mock({'2-下階柱'})
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 1
        # アクティブレイヤを下階柱レイヤに切り替えてから PIO を配置する
        vs_mock.Layer.assert_called_once_with('2-下階柱')
        args = vs_mock.CreateCustomObjectN.call_args.args
        assert args[0] == '柱束伏図記号'
        assert args[1] == (0.0, 0.0)
        assert args[2] == 0
        # showPref=False で設定ダイアログを抑止する
        # (インポート中の手動入力を不要にするため)
        assert args[3] is False
        # 検索対象レイヤ・クラス・記号サイズをパラメータに設定する
        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['TargetLayer'] == '1-柱'
        assert set_fields['TargetClass'] == ''
        assert set_fields['MarkSize'] == '300'
        # レコード名は PIO プラグイン名
        for c in vs_mock.SetRField.call_args_list:
            assert c.args[0] == 'PIO_HANDLE'
            assert c.args[1] == '柱束伏図記号'
        # 設定後にリセットして PIO の再描画 (柱検索→記号) を走らせる
        vs_mock.ResetObject.assert_called_once_with('PIO_HANDLE')

    def test_formats_integer_size_without_trailing_zero(self) -> None:
        vs_mock = _make_vs_mock({'2-下階柱'})
        vw_cm = _load(vs_mock)

        command = make_command()
        command['size'] = 450.0
        vw_cm.execute_column_marks([command])

        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['MarkSize'] == '450'

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 0
        vs_mock.CreateCustomObjectN.assert_not_called()

    def test_skips_when_pio_cannot_be_created(self) -> None:
        # プラグイン未登録などで CreateCustomObjectN が NIL を返す場合は数えない
        vs_mock = _make_vs_mock({'2-下階柱'})
        vs_mock.CreateCustomObjectN.return_value = vs_mock.Handle(0)
        vw_cm = _load(vs_mock)

        count = vw_cm.execute_column_marks([make_command()])

        assert count == 0
        vs_mock.ResetObject.assert_not_called()

    def test_passes_target_class_when_specified(self) -> None:
        vs_mock = _make_vs_mock({'2-下階柱'})
        vw_cm = _load(vs_mock)

        command = make_command()
        command['target_class'] = '04構造-02木造-03柱-02管柱'
        vw_cm.execute_column_marks([command])

        set_fields = {
            c.args[2]: c.args[3] for c in vs_mock.SetRField.call_args_list
        }
        assert set_fields['TargetClass'] == '04構造-02木造-03柱-02管柱'
