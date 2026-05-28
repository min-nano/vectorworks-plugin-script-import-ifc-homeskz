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

    def test_excludes_non_fl_storeys(self):
        """設計GL 等 "FL" で終わらないストーリは参照高なので除外する。"""
        from vectorworks_plugin_import_ifc_homeskz.story import collect_stories

        ifc = ifcopenshell.file()
        make_storey(ifc, '設計GL', 0.0)
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        make_storey(ifc, 'RFL', 5973.0)

        result = collect_stories(ifc)

        assert result == [
            (473.0, -48.0),
            (3273.0, -36.0),
            (5973.0, None),
        ]


def _make_stateful_vs_mock():
    """CreateStory/CreateLayer/CreateLevelTemplateN の作成有無を追跡するステートフルな vs モック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created = set()
    template_counter = [0]

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
    vs_mock.GetStoryElevationN.return_value = 0.0
    vs_mock.GetLayerElevationN.return_value = (0.0, 0.0)
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

        # レベルタイプが事前に登録されていること
        level_type_names = [call.args[0] for call in vs_mock.CreateLayerLevelType.call_args_list]
        assert level_type_names == ['FL', '横架材天端', '軒高']

        story_calls = [call.args for call in vs_mock.CreateStory.call_args_list]
        # 建築慣例: 一般階は階番号、最上階は "R"。空文字 suffix だと 2 回目以降失敗する
        assert story_calls == [('1階', '1'), ('2階', '2'), ('屋根', 'R')]

        # ストーリ高さは N 付き版で document units 指定
        elev_calls = [(call.args[0], call.args[1]) for call in vs_mock.SetStoryElevationN.call_args_list]
        assert elev_calls == [
            ('HANDLE_1階', 473.0),
            ('HANDLE_2階', 3273.0),
            ('HANDLE_屋根', 5973.0),
        ]

        # ストーリレベル + レイヤは Story Level Template 経由で作る
        # (AddStoryLevelN + AssociateLayerWithStory ではレイヤ→レベルの紐付けが
        # UI で <なし> になる現象を回避するため)
        template_calls = [call.args for call in vs_mock.CreateLevelTemplateN.call_args_list]
        # (layerName, scaleFactor, levelType, elevation, wallHeight)
        # レイヤ名接頭辞はストーリ suffix と一致させる ("1"/"2"/"R")
        assert ('1-FL', 1.0, 'FL', 0.0, 2400.0) in template_calls
        assert ('1-横架材天端', 1.0, '横架材天端', -48.0, 2400.0) in template_calls
        assert ('2-FL', 1.0, 'FL', 0.0, 2400.0) in template_calls
        assert ('2-横架材天端', 1.0, '横架材天端', -36.0, 2400.0) in template_calls
        assert ('R-軒高', 1.0, '軒高', 0.0, 2400.0) in template_calls

        # AddLevelFromTemplate がストーリ毎に呼ばれること
        add_calls = [call.args for call in vs_mock.AddLevelFromTemplate.call_args_list]
        # 屋根は 1 つだけ (軒高)、それ以外は 2 つ (FL, 横架材天端) = 計 5 呼び出し
        assert len(add_calls) == 5
        # 各ストーリハンドルに対して正しい回数呼ばれる
        story_call_counts = {h: 0 for h in ['HANDLE_1階', 'HANDLE_2階', 'HANDLE_屋根']}
        for h, _ in add_calls:
            story_call_counts[h] = story_call_counts.get(h, 0) + 1
        assert story_call_counts['HANDLE_1階'] == 2
        assert story_call_counts['HANDLE_2階'] == 2
        assert story_call_counts['HANDLE_屋根'] == 1

        # AddLevelFromTemplate 後にレイヤをリネーム ("1-FL-1" → "1-FL")
        rename_calls = [call.args for call in vs_mock.SetName.call_args_list]
        renamed_names = [name for _, name in rename_calls]
        assert '1-FL' in renamed_names
        assert '1-横架材天端' in renamed_names
        assert '2-FL' in renamed_names
        assert '2-横架材天端' in renamed_names
        assert 'R-軒高' in renamed_names

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
        template_calls = [call.args for call in vs_mock.CreateLevelTemplateN.call_args_list]
        assert ('R-軒高', 1.0, '軒高', 0.0, 2400.0) in template_calls
        # 屋根 (単一階扱い) の場合 FL/横架材天端 は作らない
        assert not any(c[2] in ('FL', '横架材天端') for c in template_calls)
