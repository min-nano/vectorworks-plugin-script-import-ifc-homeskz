"""柱の span(またぐレベル区間)レイヤの純関数テスト。vs 非依存。

span レイヤ名の生成・分解(``span_layer_name`` / ``parse_span_layer``)、上端が届く
to レベルの判定(``resolve_column_to_level``)、span の列挙・base 別まとめ
(``collect_column_spans`` / ``collect_column_layers_by_story``)を直接検証する。
これらは伏図の写り込み解消の中核ロジックで、フィクスチャ経由の間接検証だけでなく
規則そのものを固定して回帰を防ぐ。
"""
from __future__ import annotations

from typing import cast

from vectorworks_plugin_import_ifc_homeskz.document import ColumnCommand
from vectorworks_plugin_import_ifc_homeskz.ifc.column import (
    SPAN_LEVEL_TOL,
    collect_column_layers_by_story,
    collect_column_spans,
    resolve_column_to_level,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.story import (
    parse_span_layer,
    span_layer_name,
)


def _column(layer: str) -> ColumnCommand:
    """テスト用の最小 column 命令(span 列挙は layer だけを見る)。"""
    return cast(ColumnCommand, {'layer': layer})


class TestSpanLayerName:
    def test_integer_levels_have_no_decimal(self) -> None:
        assert span_layer_name(1, 2) == '1to2-柱'
        assert span_layer_name(1, 3) == '1to3-柱'

    def test_half_level_keeps_point_five(self) -> None:
        assert span_layer_name(2, 2.5) == '2to2.5-柱'
        assert span_layer_name(3.0, 3.5) == '3to3.5-柱'


class TestParseSpanLayer:
    def test_round_trip_integer_and_half(self) -> None:
        assert parse_span_layer('1to2-柱') == (1.0, 2.0)
        assert parse_span_layer('2to2.5-柱') == (2.0, 2.5)

    def test_non_span_layer_returns_none(self) -> None:
        # 柱以外のレイヤ・通り芯・横架材は span レイヤでない
        assert parse_span_layer('R-軒高') is None
        assert parse_span_layer('共通') is None
        assert parse_span_layer('1to2-梁') is None

    def test_malformed_core_returns_none(self) -> None:
        # 'to' が無い/数値でない core は None
        assert parse_span_layer('foo-柱') is None
        assert parse_span_layer('atob-柱') is None


class TestResolveColumnToLevel:
    # 各階の横架材(床梁)下端・天端。index は 0 起点で base 階の上の階を参照する。
    # 天端(TOPS)は下端(BOTTOMS)より梁背ぶん上。最上階(index 2)の天端は軒高。
    BOTTOMS = [590.0, 3165.0, 6120.0]
    TOPS = [830.0, 3405.0, 6400.0]

    def test_kudabashira_reaches_next_floor(self) -> None:
        # 1 階管柱: 上端が 2 階梁下端(3165)以上・2 階梁天端(3405)未満 → 次階=to 2
        to = resolve_column_to_level(0, 3300.0, self.BOTTOMS, self.TOPS)
        assert to == 2.0

    def test_roof_post_does_not_reach_next_floor(self) -> None:
        # 下屋の小屋束: 上端が直上階の梁下端(3165)未満 → 届かず from + 0.5
        to = resolve_column_to_level(1, 4000.0, self.BOTTOMS, self.TOPS)
        assert to == 2.5  # base=2 階

    def test_through_column_reaches_two_floors_up(self) -> None:
        # 通し柱(1・2 階): 上端が屋根梁下端(6120)以上・軒高(6400)未満 → 3 階床=to 3
        to = resolve_column_to_level(0, 6200.0, self.BOTTOMS, self.TOPS)
        assert to == 3.0

    def test_top_story_column_is_roof_post(self) -> None:
        # 最上階の柱(主屋根束): 上に階が無いため from + 0.5
        to = resolve_column_to_level(2, 7000.0, self.BOTTOMS, self.TOPS)
        assert to == 3.5

    def test_tolerance_counts_top_just_below_bottom_as_reached(self) -> None:
        # 下端よりわずか(許容値内)下でも到達とみなす
        top = self.BOTTOMS[1] - SPAN_LEVEL_TOL / 2
        assert resolve_column_to_level(0, top, self.BOTTOMS, self.TOPS) == 2.0

    def test_roof_post_reaching_top_story_above_eaves_is_half_level(
        self,
    ) -> None:
        # 2 階建て(1階=0, 屋根=1)。1 階に立つ小屋束で上端が軒高(屋根の横架材
        # 天端 3300)より高い → 屋根軒高の梁下端(3165)に達しても管柱ではなく
        # 屋根束 → 1to2.5(reached + 1 + 0.5)。以前は 1to2 に誤分類していた。
        bottoms = [590.0, 3165.0]
        tops = [830.0, 3300.0]  # tops[1] = 軒高
        to = resolve_column_to_level(0, 3500.0, bottoms, tops)
        assert to == 2.5

    def test_column_reaching_top_story_at_eaves_stays_integer(self) -> None:
        # 対照: 上端が軒高(3300)以下で屋根軒高の梁下端に止まる柱は管柱扱いで to 2。
        bottoms = [590.0, 3165.0]
        tops = [830.0, 3300.0]
        to = resolve_column_to_level(0, 3200.0, bottoms, tops)
        assert to == 2.0


class TestCollectColumnSpans:
    def test_distinct_and_sorted_by_from_then_to(self) -> None:
        columns = [
            _column('2to3-柱'), _column('1to2-柱'),
            _column('2to2.5-柱'), _column('2to3-柱'), _column('3to3.5-柱'),
        ]
        assert collect_column_spans(columns) == [
            (1.0, 2.0, '1to2-柱'),
            (2.0, 2.5, '2to2.5-柱'),
            (2.0, 3.0, '2to3-柱'),
            (3.0, 3.5, '3to3.5-柱'),
        ]

    def test_ignores_non_span_layers(self) -> None:
        assert collect_column_spans([_column('R-軒高')]) == []


class TestCollectColumnLayersByStory:
    def test_groups_by_base_story_index(self) -> None:
        columns = [
            _column('1to2-柱'), _column('2to2.5-柱'),
            _column('2to3-柱'), _column('3to3.5-柱'),
        ]
        # base 0 起点 index = from - 1、各階内は (from, to) 昇順
        assert collect_column_layers_by_story(columns) == {
            0: ['1to2-柱'],
            1: ['2to2.5-柱', '2to3-柱'],
            2: ['3to3.5-柱'],
        }
