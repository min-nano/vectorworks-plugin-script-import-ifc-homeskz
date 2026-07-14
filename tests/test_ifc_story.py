"""IFC 解析フェーズ (ifc.story) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc.story import (
    build_story_commands,
    collect_stories,
    get_local_placement_z,
    resolve_beam_top_offset,
)


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


class TestBuildStoryCommands:
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
        assert level_types == ['柱', '小屋束', '母屋', '軒高']

    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_story_commands(ifcopenshell.file()) == []

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0, [('IfcColumn', -48.0)])
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_story_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
