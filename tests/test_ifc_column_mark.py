"""解析フェーズ (ifc.column_mark) のテスト。vs 非依存。

柱・小屋束は span(``{from}to{to}-柱``)ごとのレイヤに配置され、各 span レイヤは単一
種別(柱=構造用途 4、小屋束=構造用途 5)。実在する span レイヤごとに、そのレイヤ自身に
重ねる**断面記号**(記号スタイル=断面)と、span の ``to`` をプレフィックスにした
``{to}-柱伏図記号`` レイヤに描く**伏図記号**(記号スタイル=平面。柱の span=柱伏図記号・
小屋束の span=束伏図記号)が組み立てられることを検証する。柱用と小屋束用は別々の
span レイヤ・別々のシンボルとして配置される。
"""
from __future__ import annotations

import json
from typing import cast

from vectorworks_plugin_import_ifc_homeskz.document import ColumnCommand
from vectorworks_plugin_import_ifc_homeskz.ifc.column_mark import (
    DEFAULT_MARK_SIZE,
    MARK_STYLE_PLAN,
    MARK_STYLE_SECTION,
    PLAN_MARK_CLASS,
    SECTION_MARK_CLASS,
    SYMBOL_COLUMN,
    SYMBOL_KOYAZUKA,
    build_column_mark_commands,
)


def _column(layer: str, structural_use: str = '4') -> ColumnCommand:
    """テスト用の最小 column 命令(build_column_mark_commands は layer と
    structural_use だけを見る)。既定は柱(構造用途 4)。"""
    return cast(ColumnCommand, {'layer': layer, 'structural_use': structural_use})


class TestBuildColumnMarkCommands:
    def test_no_columns_returns_empty(self) -> None:
        assert build_column_mark_commands([]) == []

    def test_section_mark_per_span_layer(self) -> None:
        # 実在する span レイヤごとに 1 つの断面記号(先頭にまとめて並ぶ)。
        columns = [
            _column('2to3-柱'), _column('1to2-柱'),
            _column('2to2.5-柱', '5'), _column('2to3-柱'),
            _column('3to3.5-柱', '5'),
        ]
        commands = build_column_mark_commands(columns)
        section = [c for c in commands if c['style'] == MARK_STYLE_SECTION]
        assert section == [
            {
                'layer': '1to2-柱', 'class': SECTION_MARK_CLASS,
                'target_layer': '1to2-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_SECTION,
                'symbol': '', 'position': [0.0, 0.0],
            },
            {
                'layer': '2to2.5-柱', 'class': SECTION_MARK_CLASS,
                'target_layer': '2to2.5-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_SECTION,
                'symbol': '', 'position': [0.0, 0.0],
            },
            {
                'layer': '2to3-柱', 'class': SECTION_MARK_CLASS,
                'target_layer': '2to3-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_SECTION,
                'symbol': '', 'position': [0.0, 0.0],
            },
            {
                'layer': '3to3.5-柱', 'class': SECTION_MARK_CLASS,
                'target_layer': '3to3.5-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_SECTION,
                'symbol': '', 'position': [0.0, 0.0],
            },
        ]

    def test_plan_mark_per_span_layer_with_kind_symbol(self) -> None:
        # 伏図記号は span の to をプレフィックスにした {to}-柱伏図記号 レイヤに置く。
        # シンボルはその span の種別で決める(柱=柱伏図記号・小屋束=束伏図記号)。
        # 同じ to の span(1to2.5・2to2.5)はともに 2.5-柱伏図記号 レイヤに載る。
        columns = [
            _column('1to2-柱', '4'),      # 管柱 → 柱伏図記号
            _column('1to2.5-柱', '4'),    # 柱(半整数 to だが構造用途 4)→ 柱伏図記号
            _column('2to2.5-柱', '5'),    # 小屋束 → 束伏図記号
        ]
        commands = build_column_mark_commands(columns)
        plan = [c for c in commands if c['style'] == MARK_STYLE_PLAN]
        assert plan == [
            {
                'layer': '2-柱伏図記号', 'class': PLAN_MARK_CLASS,
                'target_layer': '1to2-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_PLAN,
                'symbol': SYMBOL_COLUMN, 'position': [0.0, 0.0],
            },
            {
                'layer': '2.5-柱伏図記号', 'class': PLAN_MARK_CLASS,
                'target_layer': '1to2.5-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_PLAN,
                'symbol': SYMBOL_COLUMN, 'position': [0.0, 0.0],
            },
            {
                'layer': '2.5-柱伏図記号', 'class': PLAN_MARK_CLASS,
                'target_layer': '2to2.5-柱', 'target_class': '',
                'size': DEFAULT_MARK_SIZE, 'style': MARK_STYLE_PLAN,
                'symbol': SYMBOL_KOYAZUKA, 'position': [0.0, 0.0],
            },
        ]

    def test_section_marks_precede_plan_marks(self) -> None:
        # 断面記号をすべて先に、続けて伏図記号をすべて並べる
        commands = build_column_mark_commands([_column('1to2-柱')])
        assert [c['style'] for c in commands] == [
            MARK_STYLE_SECTION, MARK_STYLE_PLAN]
        assert commands[0]['class'] == SECTION_MARK_CLASS
        assert commands[1]['class'] == PLAN_MARK_CLASS

    def test_commands_are_json_serializable(self) -> None:
        commands = build_column_mark_commands(
            [_column('1to2-柱'), _column('2to2.5-柱', '5')])
        assert json.loads(json.dumps(commands)) == commands
