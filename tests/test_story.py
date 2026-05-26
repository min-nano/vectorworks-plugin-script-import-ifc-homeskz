import importlib
from unittest.mock import MagicMock, patch

import ifcopenshell


def make_storey(ifc, name, elevation, elements=None):
    """テスト用 IfcBuildingStorey とその配下要素を生成する。

    elements: [(ifc_type, z_offset), ...]  例 [('IfcColumn', -48.0), ('IfcSlab', -48.0)]
    """
    storey = ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)
    if elements:
        related = []
        for ifc_type, z in elements:
            point = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, z])
            axis = ifc.create_entity('IfcAxis2Placement3D', Location=point)
            placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=axis)
            elem = ifc.create_entity(ifc_type, ObjectPlacement=placement)
            related.append(elem)
        ifc.create_entity(
            'IfcRelContainedInSpatialStructure',
            RelatingStructure=storey,
            RelatedElements=related,
        )
    return storey


class TestGetLocalPlacementZ:
    def test_extracts_z_from_cartesian_point(self):
        from vectorworks_plugin_import_ifc_homeskz.story import get_local_placement_z

        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        column = storey.ContainsElements[0].RelatedElements[0]
        assert get_local_placement_z(column) == -48.0

    def test_returns_none_when_placement_missing(self):
        from vectorworks_plugin_import_ifc_homeskz.story import get_local_placement_z

        elem = MagicMock()
        elem.ObjectPlacement = None
        assert get_local_placement_z(elem) is None


class TestResolveBeamTopOffset:
    def test_finds_column_z_offset(self):
        from vectorworks_plugin_import_ifc_homeskz.story import resolve_beam_top_offset

        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        assert resolve_beam_top_offset(storey) == -48.0

    def test_finds_slab_z_offset(self):
        from vectorworks_plugin_import_ifc_homeskz.story import resolve_beam_top_offset

        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        assert resolve_beam_top_offset(storey) == -36.0

    def test_ignores_non_column_slab(self):
        from vectorworks_plugin_import_ifc_homeskz.story import resolve_beam_top_offset

        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcBeam', -100.0)])
        assert resolve_beam_top_offset(storey) == 0.0

    def test_returns_zero_when_no_elements(self):
        from vectorworks_plugin_import_ifc_homeskz.story import resolve_beam_top_offset

        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        assert resolve_beam_top_offset(storey) == 0.0


class TestCollectStories:
    def test_sorts_by_elevation_and_marks_top(self):
        from vectorworks_plugin_import_ifc_homeskz.story import collect_stories

        ifc = ifcopenshell.file()
        # わざと逆順で作成
        make_storey(ifc, 'RFL', 5973.0)
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])

        result = collect_stories(ifc)

        assert result == [
            (473.0, -48.0),
            (3273.0, -36.0),
            (5973.0, None),
        ]

    def test_empty_file_returns_empty(self):
        from vectorworks_plugin_import_ifc_homeskz.story import collect_stories

        assert collect_stories(ifcopenshell.file()) == []


def _make_stateful_vs_mock():
    """CreateStory/CreateLayer の作成有無を追跡するステートフルな vs モック。"""
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

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    return vs_mock


class TestImportStories:
    """vs モジュールをモックして import_stories() の動作を検証する。"""

    def test_creates_stories_levels_and_layers(self):
        vs_mock = _make_stateful_vs_mock()

        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        make_storey(ifc, 'RFL', 5973.0)

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.story as story_module
            importlib.reload(story_module)
            count = story_module.import_stories(ifc)

        assert count == 3

        story_names = [call.args[0] for call in vs_mock.CreateStory.call_args_list]
        assert story_names == ['1階', '2階', '屋根']

        elev_calls = [(call.args[0], call.args[1]) for call in vs_mock.SetStoryElevation.call_args_list]
        assert elev_calls == [
            ('HANDLE_1階', 473.0),
            ('HANDLE_2階', 3273.0),
            ('HANDLE_屋根', 5973.0),
        ]

        level_type_creations = [call.args[0] for call in vs_mock.CreateLevelType.call_args_list]
        assert 'FL' in level_type_creations
        assert '横架材天端' in level_type_creations
        assert '軒高' in level_type_creations

        layer_names = [call.args[0] for call in vs_mock.CreateLayer.call_args_list]
        assert layer_names == ['1-FL', '1-横架材天端', '2-FL', '2-横架材天端', '屋根-軒高']

        add_level_calls = [call.args for call in vs_mock.AddStoryLevel.call_args_list]
        assert ('HANDLE_1階', 'FL', 0.0) in add_level_calls
        assert ('HANDLE_1階', '横架材天端', -48.0) in add_level_calls
        assert ('HANDLE_2階', 'FL', 0.0) in add_level_calls
        assert ('HANDLE_2階', '横架材天端', -36.0) in add_level_calls
        assert ('HANDLE_屋根', '軒高', 0.0) in add_level_calls
        # 屋根に FL/横架材天端は作らない
        assert not any(c[0] == 'HANDLE_屋根' and c[1] in ('FL', '横架材天端') for c in add_level_calls)

        # レイヤ高さの強制上書きが正しい値で行われる
        elev_overwrite_calls = [call.args for call in vs_mock.SetLayerElevation.call_args_list]
        assert ('HANDLE_1-FL', 0.0, 0.0) in elev_overwrite_calls
        assert ('HANDLE_1-横架材天端', -48.0, 0.0) in elev_overwrite_calls
        assert ('HANDLE_屋根-軒高', 0.0, 0.0) in elev_overwrite_calls

    def test_empty_ifc_returns_zero(self):
        vs_mock = _make_stateful_vs_mock()
        ifc = ifcopenshell.file()

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.story as story_module
            importlib.reload(story_module)
            count = story_module.import_stories(ifc)

        assert count == 0
        vs_mock.CreateStory.assert_not_called()

    def test_single_story_treated_as_roof(self):
        vs_mock = _make_stateful_vs_mock()

        ifc = ifcopenshell.file()
        make_storey(ifc, 'RFL', 0.0)

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.story as story_module
            importlib.reload(story_module)
            count = story_module.import_stories(ifc)

        assert count == 1
        story_names = [call.args[0] for call in vs_mock.CreateStory.call_args_list]
        assert story_names == ['屋根']
        add_level_calls = [call.args for call in vs_mock.AddStoryLevel.call_args_list]
        assert ('HANDLE_屋根', '軒高', 0.0) in add_level_calls
