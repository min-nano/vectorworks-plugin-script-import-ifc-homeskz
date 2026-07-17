"""描画フェーズ (vw.rafter) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
import math
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import RafterCommand


def make_command() -> RafterCommand:
    # 軒側(支持点) (0,0,6000) → 棟側 (0,2730,7000)。平面投影長 2730、鉛直差 1000。
    return {
        'layer': 'R-垂木',
        'class': '04構造-02木造-05小屋組-05垂木',
        'width': 45.0,
        'height': 45.0,
        'start': [0.0, 0.0],
        'end': [0.0, 2730.0],
        'elevation': 6000.0,
        'end_elevation': 7000.0,
        'overhang': 600.0,
        'embedment': 52.5,
        'label': '45×45@455',
    }


def _make_vs_mock(existing_layers: set[str], plugin_ok: bool = True) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    obj_handle = object()
    vs_mock.CreateCustomObjectN.return_value = obj_handle if plugin_ok else null_handle
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.rafter as vw_rafter
        importlib.reload(vw_rafter)
        return vw_rafter


def _rfield(vs_mock: MagicMock) -> dict[str, str]:
    """SetRField(obj, 'FramingMember', field, value) の呼び出しを dict にまとめる。"""
    out: dict[str, str] = {}
    for call in vs_mock.SetRField.call_args_list:
        _obj, plugin, field, value = call.args
        assert plugin == 'FramingMember'
        out[field] = value
    return out


class TestExecuteRafters:
    def test_creates_framing_member_rafter(self) -> None:
        vs_mock = _make_vs_mock({'R-垂木'})
        vw_rafter = _load(vs_mock)

        count = vw_rafter.execute_rafters([make_command()])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('R-垂木')
        # 軸組ツール(FramingMember)を生成する。showPref=False で設定ダイアログを抑止。
        vs_mock.CreateCustomObjectN.assert_called_once()
        assert vs_mock.CreateCustomObjectN.call_args.args[0] == 'FramingMember'
        assert vs_mock.CreateCustomObjectN.call_args.args[3] is False
        fields = _rfield(vs_mock)
        assert fields['type'] == 'rafter'
        assert fields['width'] == '45'
        assert fields['height'] == '45'
        # 平面投影長(LineLength)は 2730
        assert float(fields['LineLength']) == 2730.0
        # 2D 表示は「幅」
        assert fields['2DDisplay'] == 'width'
        # 軒の出・差し込み・仕様ラベル・構造用途(垂木)・材質(木)
        assert float(fields['overhang']) == 600.0
        # 支持部分の差し込みは VW 登録フィールド名 bearinginset(既定 88.9mm を上書き)
        assert float(fields['bearinginset']) == 52.5
        assert fields['label'] == '45×45@455'
        assert fields['StructuralUse'] == '垂木'
        assert fields['Material'] == '木'

    def test_pitch_matches_slope(self) -> None:
        vs_mock = _make_vs_mock({'R-垂木'})
        vw_rafter = _load(vs_mock)
        vw_rafter.execute_rafters([make_command()])
        fields = _rfield(vs_mock)
        # 勾配 = atan(鉛直差 1000 / 水平長 2730)
        expected = math.degrees(math.atan2(1000.0, 2730.0))
        assert float(fields['pitch'].rstrip('°')) == expected

    def test_rotates_and_moves_to_eaves_point(self) -> None:
        vs_mock = _make_vs_mock({'R-垂木'})
        vw_rafter = _load(vs_mock)
        vw_rafter.execute_rafters([make_command()])
        # 平面方位角 = 軒(0,0)→棟(0,2730) = +90 度で回し、軒側の絶対位置へ移動する
        vs_mock.Rotate3D.assert_called_once_with(0.0, 0.0, 90.0)
        vs_mock.Move3D.assert_called_once_with(0.0, 0.0, 6000.0)

    def test_sets_class(self) -> None:
        vs_mock = _make_vs_mock({'R-垂木'})
        vw_rafter = _load(vs_mock)
        vw_rafter.execute_rafters([make_command()])
        vs_mock.SetClass.assert_called_once()
        assert vs_mock.SetClass.call_args.args[1] == '04構造-02木造-05小屋組-05垂木'

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_rafter = _load(vs_mock)

        count = vw_rafter.execute_rafters([make_command()])

        assert count == 0
        vs_mock.CreateCustomObjectN.assert_not_called()

    def test_falls_back_to_line_when_plugin_unavailable(self) -> None:
        vs_mock = _make_vs_mock({'R-垂木'}, plugin_ok=False)
        vw_rafter = _load(vs_mock)

        count = vw_rafter.execute_rafters([make_command()])

        # フォールバックでも配置数には数える
        assert count == 1
        vs_mock.LineTo.assert_called_once_with(0.0, 2730.0)

    def test_draw_returns_none_for_degenerate_rafter(self) -> None:
        # 始点=終点(平面投影長 0)の退化した命令は何も作らず None を返す
        vs_mock = _make_vs_mock({'R-垂木'})
        vw_rafter = _load(vs_mock)
        command = make_command()
        command['end'] = list(command['start'])

        assert vw_rafter.draw_rafter(command) is None
        vs_mock.CreateCustomObjectN.assert_not_called()
