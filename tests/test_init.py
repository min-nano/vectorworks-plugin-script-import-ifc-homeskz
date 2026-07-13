"""run() のエンドツーエンドテスト。

IFC 解析フェーズ (ifc) → JSON 命令セット → 描画フェーズ (vw) の
パイプライン全体を vs モックで検証する。
"""
from __future__ import annotations

import importlib
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import ifcopenshell


def _make_vs_mock() -> MagicMock:
    """ストーリ・レイヤ作成を追跡するステートフルなモック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created: set[str] = set()
    # デザインレイヤを作成順(下→上)で保持し、FLayer/NextLayer/HMoveForward を
    # モデル化する。これがないと reorder_story_layers の走査が終端しない。
    layers: list[str] = []

    def get_obj(name: str) -> object:
        if name in created:
            return 'HANDLE_' + name
        return null_handle

    def create_story(name: str, suffix: str) -> bool:
        created.add(name)
        return True

    def create_layer(name: str, layer_type: int) -> str:
        created.add(name)
        if name not in layers:
            layers.append(name)
        return 'HANDLE_' + name

    template_counter = [0]

    def create_level_template(layer_name: str, scale: float, level_type: str,
                              elev: float, wall_h: float) -> tuple[bool, int]:
        idx = template_counter[0]
        template_counter[0] += 1
        created.add(layer_name)
        if layer_name not in layers:
            layers.append(layer_name)
        return (True, idx)

    def f_layer() -> object:
        return layers[0] if layers else null_handle

    def next_layer(layer_h: Any) -> object:
        if layer_h in layers:
            i = layers.index(layer_h)
            if i + 1 < len(layers):
                return layers[i + 1]
        return null_handle

    def get_layer_by_name(name: str) -> object:
        return name if name in layers else null_handle

    def h_move_forward(layer_h: Any, to_front: bool) -> None:
        if layer_h in layers:
            i = layers.index(layer_h)
            if not to_front and i + 1 < len(layers):
                layers[i], layers[i + 1] = layers[i + 1], layers[i]

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateLevelTemplateN.side_effect = create_level_template
    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.GetLayerByName.side_effect = get_layer_by_name
    vs_mock.HMoveForward.side_effect = h_move_forward
    vs_mock.AddLevelFromTemplate.return_value = True
    vs_mock.GetLayerForStory.return_value = 'HANDLE_template_layer'
    vs_mock.LNewObj.return_value = None
    vs_mock.CreateCustomObjectPath.return_value = None
    vs_mock.GetStoryElevationN.return_value = 0.0
    vs_mock.GetLayerElevationN.return_value = (0.0, 0.0)
    return vs_mock


def _reload_vw_modules() -> None:
    """vs モックを差し替えた状態で vs 依存モジュール (vw) を再読込する。"""
    import vectorworks_plugin_import_ifc_homeskz.vw as vw
    import vectorworks_plugin_import_ifc_homeskz.vw.anchor_bolt as vw_anchor
    import vectorworks_plugin_import_ifc_homeskz.vw.column as vw_column
    import vectorworks_plugin_import_ifc_homeskz.vw.footing as vw_footing
    import vectorworks_plugin_import_ifc_homeskz.vw.grid as vw_grid
    import vectorworks_plugin_import_ifc_homeskz.vw.member as vw_member
    import vectorworks_plugin_import_ifc_homeskz.vw.sheet as vw_sheet
    import vectorworks_plugin_import_ifc_homeskz.vw.story as vw_story
    importlib.reload(vw_grid)
    importlib.reload(vw_member)
    importlib.reload(vw_story)
    importlib.reload(vw_column)
    importlib.reload(vw_footing)
    importlib.reload(vw_anchor)
    importlib.reload(vw_sheet)
    importlib.reload(vw)


class TestRun:
    def test_run_cancel(self) -> None:
        vs_mock = _make_vs_mock()
        vs_mock.GetFileN.return_value = (False, '')

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz as pkg
            pkg.run()

        vs_mock.AlrtDialog.assert_called_once_with('キャンセルされました。')

    def test_run_imports_grids_and_stories(self) -> None:
        vs_mock = _make_vs_mock()

        ifc = ifcopenshell.file()
        # 通り芯
        pts = [ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0]),
               ifc.create_entity('IfcCartesianPoint', Coordinates=[5000.0, 0.0])]
        polyline = ifc.create_entity('IfcPolyline', Points=pts)
        ifc.create_entity('IfcGridAxis', AxisTag='X1', AxisCurve=polyline, SameSense=True)
        # ストーリ (1FL + RFL)
        ifc.create_entity('IfcBuildingStorey', Name='1FL', Elevation=473.0)
        ifc.create_entity('IfcBuildingStorey', Name='RFL', Elevation=5973.0)

        fd, ifc_path = tempfile.mkstemp(suffix='.ifc')
        os.close(fd)
        ifc.write(ifc_path)

        try:
            vs_mock.GetFileN.return_value = (True, ifc_path)

            with patch.dict('sys.modules', {'vs': vs_mock}):
                _reload_vw_modules()
                import vectorworks_plugin_import_ifc_homeskz as pkg
                pkg.run()

            # 取り込み結果はステータスバー (Message) に表示する
            completion = vs_mock.Message.call_args[0][0]
            assert '1 本' in completion  # 通り芯 1 本
            assert '2 階' in completion  # 1階 + 屋根
            # 結果表示はブロッキングなアラートを使わない
            assert not any(
                '読込完了' in c.args[0] for c in vs_mock.AlrtDialog.call_args_list
            )
            # 通り芯描画用「共通」レイヤは直接 CreateLayer で作る
            created_layers = [c.args[0] for c in vs_mock.CreateLayer.call_args_list]
            assert '共通' in created_layers
            # ストーリレイヤは CreateLevelTemplateN 経由 (1-FL, R-軒高 等)
            template_layer_names = [
                c.args[0] for c in vs_mock.CreateLevelTemplateN.call_args_list
            ]
            assert '1-FL' in template_layer_names
            assert 'R-軒高' in template_layer_names
        finally:
            os.unlink(ifc_path)

    def test_run_error_handling(self) -> None:
        vs_mock = _make_vs_mock()
        vs_mock.GetFileN.return_value = (True, '/nonexistent/path/file.ifc')

        with patch.dict('sys.modules', {'vs': vs_mock}):
            _reload_vw_modules()
            import vectorworks_plugin_import_ifc_homeskz as pkg
            pkg.run()

        call_arg = vs_mock.AlrtDialog.call_args[0][0]
        assert 'エラーが発生しました' in call_arg
