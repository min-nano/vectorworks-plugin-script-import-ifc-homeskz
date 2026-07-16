"""描画フェーズ (vw.roof) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import RoofCommand


def make_command() -> RoofCommand:
    # 軒(y=0, z=6000)から棟(y=3000)へ立ち上がる 4m×3m の片流れ屋根面。
    return {
        'layer': 'R-野地板',
        'class': '04構造-02木造-06耐力面材-03屋根',
        'boundary': [[0.0, 0.0], [4000.0, 0.0], [4000.0, 3000.0], [0.0, 3000.0]],
        'axis_start': [0.0, 0.0],
        'axis_end': [4000.0, 0.0],
        'upslope': [0.0, 3000.0],
        'rise': 1000.0,
        'run': 3000.0,
        'thickness': 12.0,
        'elevation': 6000.0,
    }


def _make_vs_mock(existing_layers: set[str], plugin_ok: bool = True) -> MagicMock:
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    obj_handle = object()
    vs_mock.LNewObj.return_value = obj_handle if plugin_ok else null_handle
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.roof as vw_roof
        importlib.reload(vw_roof)
        return vw_roof


class TestExecuteRoofs:
    def test_creates_roof_with_begin_roof(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'})
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        assert count == 1
        vs_mock.Layer.assert_called_once_with('R-野地板')
        # 屋根ツール(BeginRoof)で作図し EndGroup で確定する。
        vs_mock.BeginRoof.assert_called_once()
        args = vs_mock.BeginRoof.call_args.args
        assert args[0] == (0.0, 0.0)       # axis_start (p1)
        assert args[1] == (4000.0, 0.0)    # axis_end (p2)
        assert args[2] == (0.0, 3000.0)    # upslope
        assert args[3] == 1000.0           # rise
        assert args[4] == 3000.0           # run
        vs_mock.EndGroup.assert_called_once()

    def test_sets_thickness_via_roof_attributes(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'})
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        # 厚みは SetRoofAttributes の 4 番目(roofThickDistance)引数に 12mm。
        vs_mock.SetRoofAttributes.assert_called_once()
        assert vs_mock.SetRoofAttributes.call_args.args[3] == 12.0

    def test_moves_to_eaves_elevation(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'})
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        # BeginRoof は軸を Z=0 で作るため、軒の絶対 Z へ Move3D で移動する。
        vs_mock.Move3D.assert_called_once_with(0.0, 0.0, 6000.0)

    def test_sets_class(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'})
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        vs_mock.SetClass.assert_called_once()
        assert vs_mock.SetClass.call_args.args[1] == '04構造-02木造-06耐力面材-03屋根'

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set())
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        assert count == 0
        vs_mock.BeginRoof.assert_not_called()

    def test_falls_back_to_polygon_when_roof_unavailable(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'}, plugin_ok=False)
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        # フォールバックでも配置数には数える。SetRoofAttributes は呼ばれない。
        assert count == 1
        vs_mock.SetRoofAttributes.assert_not_called()
        vs_mock.LineTo.assert_called()
