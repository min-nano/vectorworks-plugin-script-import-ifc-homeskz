"""IFC 解析フェーズ (ifc.story) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc.story import (
    build_story_commands,
    collect_stories,
    collect_story_moya_flags,
    collect_story_roof_flags,
    get_local_placement_z,
    resolve_beam_top_offset,
    story_has_moya,
    story_has_roof,
)


def add_roof_slab(
    ifc: ifcopenshell.file,
    storey: ifcopenshell.entity_instance,
    name: str = '屋根版:1_1',
) -> ifcopenshell.entity_instance:
    """指定した ``Name`` を持つ屋根版 IfcSlab を storey 配下に追加する。"""
    slab = ifc.create_entity('IfcSlab', Name=name)
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure',
        RelatingStructure=storey,
        RelatedElements=[slab],
    )
    return slab


def add_named_beam(
    ifc: ifcopenshell.file,
    storey: ifcopenshell.entity_instance,
    name: str,
) -> ifcopenshell.entity_instance:
    """指定した ``Name`` を持つ IfcBeam を storey 配下に追加する。"""
    beam = ifc.create_entity('IfcBeam', Name=name)
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure',
        RelatingStructure=storey,
        RelatedElements=[beam],
    )
    return beam


def make_storey(
    ifc: ifcopenshell.file,
    name: str,
    elevation: float,
    elements: list[tuple[str, float]] | None = None,
) -> ifcopenshell.entity_instance:
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
    def test_extracts_z_from_cartesian_point(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        column = storey.ContainsElements[0].RelatedElements[0]
        assert get_local_placement_z(column) == -48.0

    def test_returns_none_when_placement_missing(self) -> None:
        elem = MagicMock()
        elem.ObjectPlacement = None
        assert get_local_placement_z(elem) is None


class TestResolveBeamTopOffset:
    def test_finds_column_z_offset(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        assert resolve_beam_top_offset(storey) == -48.0

    def test_finds_slab_z_offset(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        assert resolve_beam_top_offset(storey) == -36.0

    def test_ignores_non_column_slab(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcBeam', -100.0)])
        assert resolve_beam_top_offset(storey) == 0.0

    def test_returns_zero_when_no_elements(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        assert resolve_beam_top_offset(storey) == 0.0

    def test_returns_maximum_offset_regardless_of_order(self) -> None:
        """複数候補があるときは列挙順に依らず床に最も近接した (0 以下の最大) 負値を返す。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0, [('IfcColumn', -36.0), ('IfcSlab', -48.0)])
        assert resolve_beam_top_offset(storey) == -36.0

        ifc2 = ifcopenshell.file()
        storey2 = make_storey(ifc2, '1FL', 473.0, [('IfcSlab', -48.0), ('IfcColumn', -36.0)])
        assert resolve_beam_top_offset(storey2) == -36.0


class TestCollectStories:
    def test_sorts_by_elevation_and_marks_top(self) -> None:
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

    def test_empty_file_returns_empty(self) -> None:
        assert collect_stories(ifcopenshell.file()) == []

    def test_excludes_non_fl_storeys(self) -> None:
        """設計GL 等 "FL" で終わらないストーリは参照高なので除外する。"""
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


class TestStoryHasMoya:
    def test_true_when_moya_named_beam_present(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '2FL', 3273.0)
        add_named_beam(ifc, storey, '木梁:母屋:1_1')
        assert story_has_moya(storey) is True

    def test_true_when_munagi_named_beam_present(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '2FL', 3273.0)
        add_named_beam(ifc, storey, '木梁:棟木:1_1')
        assert story_has_moya(storey) is True

    def test_false_when_only_ordinary_beams(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        add_named_beam(ifc, storey, '木梁:胴差:1_1')
        add_named_beam(ifc, storey, '木梁:床大梁:1_1')
        assert story_has_moya(storey) is False


class TestCollectStoryMoyaFlags:
    def test_flags_follow_elevation_order(self) -> None:
        ifc = ifcopenshell.file()
        # わざと逆順で作成
        roof = make_storey(ifc, 'RFL', 5973.0)
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        second = make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        # 中間階(2FL)に下屋根の母屋、最上階(RFL)に主屋根の母屋
        add_named_beam(ifc, second, '木梁:母屋:1_1')
        add_named_beam(ifc, roof, '木梁:母屋:2_1')
        # 1FL は母屋を持たない
        assert collect_story_moya_flags(ifc) == [False, True, True]


class TestStoryHasRoof:
    def test_true_when_roof_slab_present(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '2FL', 3273.0)
        add_roof_slab(ifc, storey, '屋根版:1_1')
        assert story_has_roof(storey) is True

    def test_false_for_non_roof_slab(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        add_roof_slab(ifc, storey, '床版:1')
        assert story_has_roof(storey) is False

    def test_collect_roof_flags_follow_elevation_order(self) -> None:
        ifc = ifcopenshell.file()
        roof = make_storey(ifc, 'RFL', 5973.0)
        make_storey(ifc, '1FL', 473.0)
        second = make_storey(ifc, '2FL', 3273.0)
        add_roof_slab(ifc, second, '屋根版:1_1')   # 下屋根
        add_roof_slab(ifc, roof, '屋根版:2_1')      # 主屋根
        assert collect_story_roof_flags(ifc) == [False, True, True]


class TestBuildStoryCommands:
    def test_shed_dormer_without_moya_gets_taruki_but_no_moya(self) -> None:
        """母屋の無い下屋根(屋根版のみ)の階は垂木レベルだけを持つ。"""
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        second = make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        add_roof_slab(ifc, second, '屋根版:1_1')  # 母屋は追加しない
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_story_commands(ifc)

        # 2 階は屋根版を持つが母屋を持たないため、垂木レベルのみ(母屋レベルなし)。
        # 垂木は横架材天端の直上に積む。
        assert commands[1]['name'] == '2階'
        assert [lv['type'] for lv in commands[1]['levels']] == [
            '柱', 'FL', '下階柱', '野地板', '垂木', '横架材天端']

    def test_intermediate_story_with_moya_gets_moya_level(self) -> None:
        """下屋根の母屋を含む中間階には 母屋 レベルが横架材天端の直上に入る。"""
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        second = make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        add_named_beam(ifc, second, '木梁:母屋:1_1')
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_story_commands(ifc)

        # 中間階(2階)は 母屋 レベルを横架材天端の直前に持ち、高さは横架材天端に揃える
        assert commands[1]['name'] == '2階'
        assert commands[1]['levels'] == [
            {'type': '柱', 'offset': -36.0, 'layer': '2-柱'},
            {'type': 'FL', 'offset': 0.0, 'layer': '2-FL'},
            {'type': '下階柱', 'offset': -36.0, 'layer': '2-下階柱'},
            {'type': '母屋', 'offset': -36.0, 'layer': '2-母屋'},
            {'type': '横架材天端', 'offset': -36.0, 'layer': '2-横架材天端'},
        ]
        # 母屋を持たない 1 階は従来どおり
        assert [lv['type'] for lv in commands[0]['levels']] == [
            '柱', 'FL', '横架材天端']

    def test_builds_commands_for_three_stories(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, '2FL', 3273.0, [('IfcSlab', -36.0)])
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_story_commands(ifc)

        assert commands == [
            {
                'name': '1階', 'suffix': '1', 'elevation': 473.0,
                'levels': [
                    {'type': '柱', 'offset': -48.0, 'layer': '1-柱'},
                    {'type': 'FL', 'offset': 0.0, 'layer': '1-FL'},
                    {'type': '横架材天端', 'offset': -48.0, 'layer': '1-横架材天端'},
                ],
            },
            {
                'name': '2階', 'suffix': '2', 'elevation': 3273.0,
                'levels': [
                    {'type': '柱', 'offset': -36.0, 'layer': '2-柱'},
                    {'type': 'FL', 'offset': 0.0, 'layer': '2-FL'},
                    {'type': '下階柱', 'offset': -36.0, 'layer': '2-下階柱'},
                    {'type': '横架材天端', 'offset': -36.0, 'layer': '2-横架材天端'},
                ],
            },
            {
                'name': '屋根', 'suffix': 'R', 'elevation': 5973.0,
                'levels': [
                    {'type': '柱', 'offset': 0.0, 'layer': 'R-柱'},
                    {'type': '下階柱', 'offset': 0.0, 'layer': 'R-下階柱'},
                    {'type': '小屋束', 'offset': 0.0, 'layer': 'R-小屋束'},
                    {'type': '野地板', 'offset': 0.0, 'layer': 'R-野地板'},
                    {'type': '垂木', 'offset': 0.0, 'layer': 'R-垂木'},
                    {'type': '母屋', 'offset': 0.0, 'layer': 'R-母屋'},
                    {'type': '軒高', 'offset': 0.0, 'layer': 'R-軒高'},
                ],
            },
        ]

    def test_single_story_treated_as_roof(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, 'RFL', 0.0)

        commands = build_story_commands(ifc)

        assert len(commands) == 1
        assert commands[0]['name'] == '屋根'
        assert commands[0]['suffix'] == 'R'
        level_types = [level['type'] for level in commands[0]['levels']]
        assert level_types == ['柱', '小屋束', '野地板', '垂木', '母屋', '軒高']

    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_story_commands(ifcopenshell.file()) == []

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_story_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
