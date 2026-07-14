"""解析フェーズ (ifc.column_mark) のテスト。vs 非依存。

各階の下階柱記号 (柱束伏図記号 PIO) の命令が、直下階 (N-1) の柱レイヤを検索対象に
して横架材天端の直上レイヤ (n-下階柱) に組み立てられること、および最上階の
小屋束記号が屋根の柱レイヤ (R-柱) を小屋束クラスで絞って R-小屋束 レイヤに
組み立てられることを検証する。
"""
from __future__ import annotations

import json

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.ifc.column_mark import (
    DEFAULT_MARK_SIZE,
    build_column_mark_commands,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
    CLASS_KOYAZUKA,
    CLASS_KUDABASHIRA,
)


def make_storey(
    ifc: ifcopenshell.file, name: str, elevation: float
) -> ifcopenshell.entity_instance:
    return ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)


class TestBuildColumnMarkCommands:
    def test_empty_ifc_returns_empty(self) -> None:
        assert build_column_mark_commands(ifcopenshell.file()) == []

    def test_single_story_only_koyazuka_mark(self) -> None:
        # ストーリが 1 つだけ (=最上階=最下階) なら下階柱記号は作らないが、
        # 屋根の小屋束を母屋伏図に記号化する小屋束記号は作る
        ifc = ifcopenshell.file()
        make_storey(ifc, 'RFL', 0.0)
        assert build_column_mark_commands(ifc) == [
            {
                'layer': 'R-小屋束', 'target_layer': 'R-柱',
                'target_class': CLASS_KOYAZUKA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
        ]

    def test_three_stories_skip_lowest_plus_koyazuka(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, '2FL', 3273.0)
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_column_mark_commands(ifc)

        # 最下階 (1階) の下階柱記号は作らない。2階・屋根の各階に管柱(×)と小屋束(○)の
        # 2 つずつ (計 4 つ)、加えて屋根の小屋束記号 1 つ
        assert commands == [
            {
                'layer': '2-下階柱', 'target_layer': '1-柱',
                'target_class': CLASS_KUDABASHIRA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
            {
                'layer': '2-下階柱', 'target_layer': '1-柱',
                'target_class': CLASS_KOYAZUKA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
            {
                'layer': 'R-下階柱', 'target_layer': '2-柱',
                'target_class': CLASS_KUDABASHIRA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
            {
                'layer': 'R-下階柱', 'target_layer': '2-柱',
                'target_class': CLASS_KOYAZUKA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
            {
                'layer': 'R-小屋束', 'target_layer': 'R-柱',
                'target_class': CLASS_KOYAZUKA, 'size': DEFAULT_MARK_SIZE,
                'position': [0.0, 0.0],
            },
        ]

    def test_targets_directly_lower_story_columns(self) -> None:
        # 3 階建て: 各階の下階柱記号が直下階の柱レイヤを指し、末尾に屋根の小屋束記号
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 500.0)
        make_storey(ifc, '2FL', 3300.0)
        make_storey(ifc, '3FL', 6100.0)
        make_storey(ifc, 'RFL', 8900.0)

        commands = build_column_mark_commands(ifc)

        # 各下階柱記号は管柱(×)と小屋束(○)の 2 クラスに分かれる。末尾に屋根の小屋束記号。
        assert [
            (c['layer'], c['target_layer'], c['target_class']) for c in commands
        ] == [
            ('2-下階柱', '1-柱', CLASS_KUDABASHIRA),
            ('2-下階柱', '1-柱', CLASS_KOYAZUKA),
            ('3-下階柱', '2-柱', CLASS_KUDABASHIRA),
            ('3-下階柱', '2-柱', CLASS_KOYAZUKA),
            ('R-下階柱', '3-柱', CLASS_KUDABASHIRA),
            ('R-下階柱', '3-柱', CLASS_KOYAZUKA),
            ('R-小屋束', 'R-柱', CLASS_KOYAZUKA),
        ]

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)

        commands = build_column_mark_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
