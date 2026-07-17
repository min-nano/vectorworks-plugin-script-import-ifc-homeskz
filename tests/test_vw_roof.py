"""描画フェーズ (vw.roof) のテスト。vs をモックし手書きの命令で検証する。"""
from __future__ import annotations

import importlib
import math
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import RoofCommand

# GetTypeN のタイプ番号: 2D ポリゴン(テンプレート/フォールバック外形)。
_POLYGON_TYPE = 5
# 屋根オブジェクトのタイプ番号(ポリゴン以外なら何でもよい。実値は VW 依存)。
_ROOF_TYPE = 89
# 退避・復元される作図レイヤの Z/ΔZ(モックの GetZVals が返す値)。
_SAVED_Z_VALS = (100.0, 20.0)


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


def _make_vs_mock(
    existing_layers: set[str],
    created: object | None = None,
    created_type: int = _ROOF_TYPE,
) -> MagicMock:
    """vs モックを作る。

    ``created`` は BeginRoof + テンプレート + EndGroup の後に LNewObj が返す
    オブジェクト(None なら「何も作られない」= LNewObj は常に NIL)。
    ``created_type`` はそのオブジェクトの GetTypeN が返すタイプ番号
    (屋根=ポリゴン以外、テンプレートのポリゴンが残った失敗時=5)。
    draw_roof は BeginRoof の前に LNewObj で直前のオブジェクトを記録し前後比較で
    成否を判定するため、LNewObj は 1 回目(前)= NIL、2 回目以降(後)= created を返す。
    """
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    def get_obj(name: str) -> object:
        return ('HANDLE_' + name) if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.GetZVals.return_value = _SAVED_Z_VALS
    # 既定では屋根の軸 Z(レイヤ相対)は目標(軒高 6000 − レイヤ Z 100 = 5900)に
    # 一致 = 自己補正は不要。
    vs_mock.GetRoofFaceCoords.return_value = (
        (0.0, 0.0), (4000.0, 0.0), 5900.0, (0.0, 3000.0))
    vs_mock.GetRoofFaceAttrib.return_value = (8.467, 25.4, 1, 0, 3.795, 12.0)

    calls = {'n': 0}

    def lnewobj() -> object:
        calls['n'] += 1
        if calls['n'] == 1 or created is None:
            return null_handle
        return created

    vs_mock.LNewObj.side_effect = lnewobj
    vs_mock.GetTypeN.return_value = created_type
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.roof as vw_roof
        importlib.reload(vw_roof)
        return vw_roof


class TestExecuteRoofs:
    def test_creates_roof_with_begin_roof(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
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
        # rise/run は比(勾配)を保ったまま run=25.4(1 インチ)基準に正規化して渡す
        # (VW のエクスポートの規約。命令の rise=1000/run=3000 → rise=8.466…)。
        assert args[3] == pytest.approx(1000.0 * 25.4 / 3000.0)  # rise
        assert args[4] == 25.4                                   # run
        # vertPart = 厚み×sinθ(エクスポートと同じ計算)。
        assert args[6] == pytest.approx(
            12.0 * 1000.0 / math.hypot(1000.0, 3000.0))
        vs_mock.EndGroup.assert_called_once()

    def test_sets_thickness_via_zvals_without_touching_z(self) -> None:
        # 厚みは SetZVals の ΔZ が担う。Z はレイヤの値を維持し(バインドされた
        # レイヤでは変更が効かないため依存しない)、作成後に退避値へ復元する
        # (SetRoofAttributes は使わない。エクスポートの正規手順。#113)。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        assert vs_mock.SetZVals.call_args_list == [
            call(_SAVED_Z_VALS[0], 12.0),
            call(_SAVED_Z_VALS[0], _SAVED_Z_VALS[1]),
        ]
        vs_mock.SetRoofAttributes.assert_not_called()

    def test_moves_to_eaves_elevation_before_end_group(self) -> None:
        # 軒の目標 Z はレイヤ相対(絶対 6000 − レイヤ Z 100 = 5900)。エクスポートと
        # 同じく BeginRoof 直後(EndGroup の前)に Move3D を呼ぶ。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        vs_mock.Move3D.assert_called_once_with(0.0, 0.0, 5900.0)
        names = [c[0] for c in vs_mock.mock_calls]
        assert names.index('BeginRoof') < names.index('Move3D')
        assert names.index('Move3D') < names.index('EndGroup')

    def test_corrects_axis_z_when_roof_lands_at_layer_height(self) -> None:
        # 屋根はレイヤ平面(レイヤ相対 Zaxis=0 = 軒高・地廻り)に作られる。実測
        # (GetRoofFaceCoords の Zaxis、レイヤ相対)と目標のレイヤ相対 Z
        # (絶対 6000 − レイヤ Z 100 = 5900)の差分だけ確定後に Move3D で補正する。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vs_mock.GetRoofFaceCoords.return_value = (
            (0.0, 0.0), (4000.0, 0.0), 1000.0, (0.0, 3000.0))
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        # 1 回目 = 作成中の Move3D(レイヤ相対 5900)、2 回目 = 自己補正
        # (実測 1000 → 5900 の差分 +4900)。
        assert vs_mock.Move3D.call_args_list == [
            call(0.0, 0.0, 5900.0),
            call(0.0, 0.0, 4900.0),
        ]
        names = [c[0] for c in vs_mock.mock_calls]
        assert names.index('EndGroup') < len(names) - 1 - names[::-1].index(
            'Move3D')  # 補正の Move3D は EndGroup の後

    def test_corrects_axis_z_with_flat_coords_tuple(self) -> None:
        # GetRoofFaceCoords が座標を平坦な 7 要素で返す環境でも Zaxis を解釈する。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vs_mock.GetRoofFaceCoords.return_value = (
            0.0, 0.0, 4000.0, 0.0, 5800.0, 0.0, 3000.0)
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        assert vs_mock.Move3D.call_args_list[-1] == call(0.0, 0.0, 100.0)

    def test_no_correction_when_coords_unusable(self) -> None:
        # GetRoofFaceCoords が解釈できない値を返す場合は補正しない
        # (作成中の Move3D の 1 回だけ)。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vs_mock.GetRoofFaceCoords.return_value = None
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        assert vs_mock.Move3D.call_args_list == [call(0.0, 0.0, 5900.0)]

    def test_no_correction_when_axis_z_matches(self) -> None:
        # 実測 Zaxis が目標のレイヤ相対 Z と一致(既定モック)なら補正は行わない。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        assert vs_mock.Move3D.call_args_list == [call(0.0, 0.0, 5900.0)]

    def test_sets_class(self) -> None:
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        vs_mock.SetClass.assert_called_once()
        assert vs_mock.SetClass.call_args.args[1] == '04構造-02木造-06耐力面材-03屋根'

    def test_sets_all_attributes_by_class(self) -> None:
        # 屋根の描画属性(太さ・色・パターン・透明度等)をすべてクラス属性に従わせる。
        roof_handle = object()
        vs_mock = _make_vs_mock({'R-野地板'}, created=roof_handle)
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        vs_mock.SetPenColorByClass.assert_called_once_with(roof_handle)
        vs_mock.SetFillColorByClass.assert_called_once_with(roof_handle)
        vs_mock.SetLWByClass.assert_called_once_with(roof_handle)
        vs_mock.SetLSByClass.assert_called_once_with(roof_handle)
        vs_mock.SetFPatByClass.assert_called_once_with(roof_handle)
        vs_mock.SetMarkerByClass.assert_called_once_with(roof_handle)
        vs_mock.SetOpacityByClass.assert_called_once_with(roof_handle)

    def test_does_not_touch_finished_roof_except_class(self) -> None:
        # 確定後の屋根への後付け操作は SetClass のみ(SetRoofAttributes・
        # Move3DObj・ResetObject は未定義動作でクラッシュの一因になるため
        # 呼ばない。#113)。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vw_roof = _load(vs_mock)
        vw_roof.execute_roofs([make_command()])
        vs_mock.SetRoofAttributes.assert_not_called()
        vs_mock.Move3DObj.assert_not_called()
        vs_mock.ResetObject.assert_not_called()

    def test_skips_when_layer_missing(self) -> None:
        vs_mock = _make_vs_mock(set(), created=object())
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        assert count == 0
        vs_mock.BeginRoof.assert_not_called()

    def test_falls_back_to_polygon_when_roof_unavailable(self) -> None:
        # LNewObj が NIL のまま = 屋根もテンプレートも作られない環境。
        vs_mock = _make_vs_mock({'R-野地板'}, created=None)
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        # フォールバックでも配置数には数える。屋根専用の設定は呼ばれない。
        assert count == 1
        vs_mock.SetRoofAttributes.assert_not_called()
        vs_mock.LineTo.assert_called()
        # レイヤの Z/ΔZ は復元される。
        assert vs_mock.SetZVals.call_args_list[-1] == call(
            _SAVED_Z_VALS[0], _SAVED_Z_VALS[1])

    def test_degenerate_run_falls_back_without_begin_roof(self) -> None:
        # run<=0(鉛直面等の退化した命令)は勾配が定まらないため BeginRoof を
        # 呼ばず、外形ポリゴンのフォールバックにとどめる。
        vs_mock = _make_vs_mock({'R-野地板'}, created=None)
        vw_roof = _load(vs_mock)
        command = make_command()
        command['run'] = 0.0

        count = vw_roof.execute_roofs([command])

        assert count == 1
        vs_mock.BeginRoof.assert_not_called()
        vs_mock.SetZVals.assert_not_called()
        vs_mock.LineTo.assert_called()

    def test_leftover_template_polygon_is_not_treated_as_roof(self) -> None:
        # BeginRoof が屋根を作れずテンプレートの外形ポリゴンだけが残った場合、
        # LNewObj は NIL ではなくそのポリゴンを返す。ポリゴンを屋根と誤認しない
        # ようタイプ判別でフォールバック扱いにし、クラス設定だけを行う(#113)。
        poly_handle = object()
        vs_mock = _make_vs_mock(
            {'R-野地板'}, created=poly_handle, created_type=_POLYGON_TYPE)
        vw_roof = _load(vs_mock)

        count = vw_roof.execute_roofs([make_command()])

        assert count == 1
        vs_mock.SetRoofAttributes.assert_not_called()
        vs_mock.Move3DObj.assert_not_called()
        vs_mock.SetClass.assert_called_once()
        assert vs_mock.SetClass.call_args.args[0] is poly_handle

    def test_restores_zvals_when_getzvals_unavailable(self) -> None:
        # GetZVals がタプルを返さない環境では既定の (0,0) を退避値として扱う
        # (Z=0 のまま厚みだけ設定し、(0,0) へ復元する)。
        vs_mock = _make_vs_mock({'R-野地板'}, created=object())
        vs_mock.GetZVals.return_value = None
        vw_roof = _load(vs_mock)

        vw_roof.execute_roofs([make_command()])

        assert vs_mock.SetZVals.call_args_list == [
            call(0.0, 12.0),
            call(0.0, 0.0),
        ]
