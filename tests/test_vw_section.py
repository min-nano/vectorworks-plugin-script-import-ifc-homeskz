"""描画フェーズ (vw.section) のテスト。vs をモックし手書きの命令で検証する。

既製の断面指示線(Section Line2 PIO)X1/X2/Y1 とそのビューポートをモデル化し、
execute_sections が指示線を検索・移動・回転・改名し、リンク先ビューポートを改名し、
使わない分を削除し、残りを整列することを検証する。
"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import SectionCommand


def make_command(
    direction: str, source: str, number: str,
    line_start: list[float], line_end: list[float],
) -> SectionCommand:
    return {
        'direction': direction,
        'source_number': source,
        'drawing_number': number,
        'drawing_title': f'{number}通り',
        'line_start': line_start,
        'line_end': line_end,
    }


def _make_vs_mock(premade_numbers: list[str]) -> MagicMock:
    """既製の断面指示線群をモデル化した vs モック。

    各図番に指示線ハンドル(タプル)を割り当て、FInLayer/NextObj で列挙、GetRField で
    Drawing Number / Linked To を返し、GetObject でリンク先ビューポートを解決する。
    """
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    lines = {num: ('LINE', num) for num in premade_numbers}
    line_handles = list(lines.values())
    handle_to_num = {h: n for n, h in lines.items()}
    # 1 つのデザインレイヤに全指示線を置く
    design_layer = 'LAYER'

    def f_layer() -> object:
        return design_layer

    def next_layer(_h: Any) -> object:
        return null_handle

    def f_in_layer(_layer_h: Any) -> Any:
        return line_handles[0] if line_handles else null_handle

    def next_obj(obj: Any) -> Any:
        if obj in handle_to_num:
            i = line_handles.index(obj)
            return line_handles[i + 1] if i + 1 < len(line_handles) else null_handle
        return null_handle

    def get_rfield(h: Any, record: str, field: str) -> str:
        if record == 'Section Line2' and h in handle_to_num:
            if field == 'Drawing Number':
                return handle_to_num[h]
            if field == 'Linked To':
                return f'{handle_to_num[h]}/A'
        return ''

    def get_obj(name: str) -> Any:
        if isinstance(name, str) and name.endswith('/A'):
            return ('VP', name)
        return null_handle

    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.FInLayer.side_effect = f_in_layer
    vs_mock.NextObj.side_effect = next_obj
    vs_mock.GetRField.side_effect = get_rfield
    vs_mock.GetObject.side_effect = get_obj
    vs_mock.GetBBox.return_value = ((0.0, 0.0), (0.0, 0.0))
    return vs_mock


def _load(vs_mock: MagicMock) -> Any:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.section as vw_section
        importlib.reload(vw_section)
        return vw_section


class TestExecuteSections:
    def test_places_and_returns_count(self) -> None:
        vs_mock = _make_vs_mock(['X1', 'X2', 'Y1'])
        vw_section = _load(vs_mock)
        cmds = [
            make_command('X', 'X1', 'X1', [-4000.0, -4000.0], [-4000.0, 4000.0]),
            make_command('Y', 'Y1', 'い', [-5000.0, -3000.0], [5000.0, -3000.0]),
        ]
        assert vw_section.execute_sections(cmds) == 2

    def test_empty_returns_zero_without_scan(self) -> None:
        vs_mock = _make_vs_mock(['X1'])
        vw_section = _load(vs_mock)
        assert vw_section.execute_sections([]) == 0
        vs_mock.FInLayer.assert_not_called()

    def test_x_line_rotated_y_not(self) -> None:
        vs_mock = _make_vs_mock(['X1', 'Y1'])
        vw_section = _load(vs_mock)
        vw_section.execute_sections([
            make_command('X', 'X1', 'X1', [-4000.0, -4000.0], [-4000.0, 4000.0]),
            make_command('Y', 'Y1', 'い', [-5000.0, -3000.0], [5000.0, -3000.0]),
        ])
        # X通りは 90 度回転、Y通りは回転しない → HRotate は 1 回だけ
        assert vs_mock.HRotate.call_count == 1
        assert vs_mock.HRotate.call_args.args[2] == vw_section._ROTATE_X_DEG

    def test_renames_line_and_viewport(self) -> None:
        vs_mock = _make_vs_mock(['Y1'])
        vw_section = _load(vs_mock)
        vw_section.execute_sections([
            make_command('Y', 'Y1', 'い', [-5000.0, -3000.0], [5000.0, -3000.0]),
        ])
        # 指示線の図番・タイトルを新しい通り名に変更する
        rfield_calls = [c.args for c in vs_mock.SetRField.call_args_list]
        assert (('LINE', 'Y1'), 'Section Line2', 'Drawing Number', 'い') in rfield_calls
        assert (('LINE', 'Y1'), 'Section Line2', 'Drawing Title', 'い通り') in rfield_calls
        # リンク先ビューポートの図番・図面タイトルも合わせる
        ov_calls = [c.args for c in vs_mock.SetObjectVariableString.call_args_list]
        assert (('VP', 'Y1/A'), vw_section._OV_VP_DRAWING_NUMBER, 'い') in ov_calls
        assert (('VP', 'Y1/A'), vw_section._OV_VP_DRAWING_TITLE, 'い通り') in ov_calls

    def test_deletes_unused_premade(self) -> None:
        vs_mock = _make_vs_mock(['X1', 'X2', 'X3', 'Y1'])
        vw_section = _load(vs_mock)
        # X1 のみ使用 → X2, X3, Y1 の指示線とビューポートを削除する
        vw_section.execute_sections([
            make_command('X', 'X1', 'X1', [-4000.0, -4000.0], [-4000.0, 4000.0]),
        ])
        deleted = {c.args[0] for c in vs_mock.DelObject.call_args_list}
        assert ('LINE', 'X2') in deleted
        assert ('LINE', 'X3') in deleted
        assert ('LINE', 'Y1') in deleted
        assert ('VP', 'X2/A') in deleted
        # 使用した X1 は削除しない
        assert ('LINE', 'X1') not in deleted

    def test_skips_missing_source(self) -> None:
        vs_mock = _make_vs_mock(['X1'])
        vw_section = _load(vs_mock)
        # source X5 は存在しない → 配置 0
        count = vw_section.execute_sections([
            make_command('X', 'X5', 'X5', [0.0, -4000.0], [0.0, 4000.0]),
        ])
        assert count == 0
