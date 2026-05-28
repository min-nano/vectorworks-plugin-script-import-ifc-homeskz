import importlib
import os
import tempfile
from unittest.mock import MagicMock, patch

import ifcopenshell


def _make_vs_mock():
    """ストーリ・レイヤ作成を追跡するステートフルなモック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created = set()

    def get_obj(name):
        if name in created:
            return 'HANDLE_' + name
        return null_handle

    def create_story(name, suffix):
        created.add(name)
        return True

    def create_layer(name, layer_type):
        created.add(name)
        return 'HANDLE_' + name

    template_counter = [0]

    def create_level_template(layer_name, scale, level_type, elev, wall_h):
        idx = template_counter[0]
        template_counter[0] += 1
        return (True, idx)

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateLevelTemplateN.side_effect = create_level_template
    vs_mock.AddLevelFromTemplate.return_value = True
    vs_mock.GetLayerForStory.return_value = 'HANDLE_template_layer'
    vs_mock.LNewObj.return_value = None
    vs_mock.CreateCustomObjectPath.return_value = None
    vs_mock.GetStoryElevationN.return_value = 0.0
    vs_mock.GetLayerElevationN.return_value = (0.0, 0.0)
    return vs_mock


def _reload_package():
    import vectorworks_plugin_import_ifc_homeskz as pkg
    import vectorworks_plugin_import_ifc_homeskz.grid as grid_module
    import vectorworks_plugin_import_ifc_homeskz.member as member_module
    import vectorworks_plugin_import_ifc_homeskz.story as story_module
    importlib.reload(grid_module)
    importlib.reload(member_module)
    importlib.reload(story_module)
    importlib.reload(pkg)
    return pkg


class TestRun:
    def test_run_cancel(self):
        vs_mock = _make_vs_mock()
        vs_mock.GetFileN.return_value = (False, '')

        with patch.dict('sys.modules', {'vs': vs_mock}):
            pkg = _reload_package()
            pkg.run()

        vs_mock.AlrtDialog.assert_called_once_with('キャンセルされました。')

    def test_run_imports_grids_and_stories(self):
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
                pkg = _reload_package()
                pkg.run()

            completion = vs_mock.AlrtDialog.call_args[0][0]
            assert '1 本' in completion  # 通り芯 1 本
            assert '2 階' in completion  # 1階 + 屋根
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

    def test_run_error_handling(self):
        vs_mock = _make_vs_mock()
        vs_mock.GetFileN.return_value = (True, '/nonexistent/path/file.ifc')

        with patch.dict('sys.modules', {'vs': vs_mock}):
            pkg = _reload_package()
            pkg.run()

        call_arg = vs_mock.AlrtDialog.call_args[0][0]
        assert 'エラーが発生しました' in call_arg
