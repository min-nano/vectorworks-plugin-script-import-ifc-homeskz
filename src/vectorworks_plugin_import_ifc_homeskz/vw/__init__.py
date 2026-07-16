"""フェーズ2: VectorWorks 描画。

JSON 命令セット(``document.py`` のスキーマ参照)に従って vs モジュールで
実際の描画を行う。このパッケージだけが vs に依存し、IFC や ifcopenshell の
知識は持たない。
"""
from __future__ import annotations

from typing import Any

from ..document import validate_document
from .anchor_bolt import execute_anchor_bolts
from .column import execute_columns
from .column_mark import execute_column_marks
from .fire_brace import execute_fire_braces
from .floor import execute_floors
from .floor_post import execute_floor_posts
from .footing import execute_slabs, execute_wall_joins, execute_walls
from .grid import execute_grids
from .member import execute_members
from .rafter import execute_rafters
from .rebar import execute_rebars
from .roof import execute_roofs
from .sheet import execute_sheets
from .story import execute_stories, reorder_story_layers

__all__ = ['execute_anchor_bolts', 'execute_column_marks', 'execute_columns',
           'execute_document', 'execute_fire_braces', 'execute_floor_posts',
           'execute_floors', 'execute_grids', 'execute_members',
           'execute_rafters', 'execute_rebars', 'execute_roofs',
           'execute_sheets', 'execute_slabs', 'execute_stories',
           'execute_wall_joins', 'execute_walls', 'reorder_story_layers']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 垂木 → 野地板 → 柱 → 立上り → 壁結合 → 底盤 → アンカーボルト → 床束 → 火打 → 下階柱記号 → シートの順で描画する。

    構造材などの描画後に reorder_story_layers でデザインレイヤのスタック順を整える。
    通り芯レイヤ(共通)を最上段に積むため、その生成(通り芯描画)後に並べ替える
    必要がある。シート(ビューポート)はデザインレイヤを参照するため、それらの生成後
    (並べ替え後)に描画する。下階柱記号(柱束伏図記号 PIO)は配置後のリセットで
    直下階の柱を検索するため、柱の描画後に配置する。壁結合(execute_wall_joins)は
    立上りの壁ハンドルを参照するため、立上りをすべて配置した直後に実行する。

    Returns: {'stories', 'grids', 'members', 'rafters', 'roofs', 'columns',
        'walls', 'wall_joins', 'slabs', 'floors', 'rebars', 'anchor_bolts',
        'floor_posts', 'fire_braces', 'column_marks', 'sheets', 'tags',
        'legends'}
        各命令の実行数。rafters は屋根版から導出した垂木(軸組)数、roofs は
        屋根版から導出した野地板(屋根オブジェクト)数、wall_joins は
        交差する立上りを結合した回数、slabs は底盤・地中梁数、floors は各階 FL
        レイヤに配置した床板(床)数、rebars は基礎に配置した配筋 PIO(鉄筋)数、
        floor_posts は大引下に配置した床束シンボル数、fire_braces は
        横架材レイヤに配置した火打シンボル数、column_marks は下階柱レイヤに配置した
        柱束伏図記号 PIO 数、tags は伏図ビューポートに配置した断面寸法データタグ数、
        legends は基礎伏図に配置したグラフィック凡例数。
    """
    validated = validate_document(document)
    # 横架材のハンドルを記録し、断面寸法データタグ(シートフェーズ)の関連付けに使う
    member_handles: dict[int, Any] = {}
    # 立上りのハンドルを記録し、壁結合(execute_wall_joins)の関連付けに使う
    wall_handles: dict[int, Any] = {}
    counts = {
        'stories': execute_stories(validated['stories']),
        'grids': execute_grids(validated['grids']),
        'members': execute_members(validated['members'], member_handles),
        # 垂木は屋根版から導出した軸組ツール(FramingMember)。母屋の直上の
        # n-垂木 レイヤに配置する(レイヤは story 命令が生成)。
        'rafters': execute_rafters(validated['rafters']),
        # 野地板は屋根版から導出した屋根ツール(BeginRoof)。垂木の直上の
        # n-野地板 レイヤに配置する(レイヤは story 命令が生成)。
        'roofs': execute_roofs(validated['roofs']),
        'columns': execute_columns(validated['columns']),
        'walls': execute_walls(validated['walls'], wall_handles),
        # 立上りをすべて配置した後に交差する壁同士を結合する
        'wall_joins': execute_wall_joins(validated['wall_joins'], wall_handles),
        'slabs': execute_slabs(validated['slabs']),
        # 床板(床ツール)は各階の FL レイヤに配置する
        'floors': execute_floors(validated['floors']),
        # 基礎の配筋(鉄筋 PIO)は立上り・底盤と同じレイヤに重ねる
        'rebars': execute_rebars(validated['rebars']),
        'anchor_bolts': execute_anchor_bolts(validated['anchor_bolts']),
        'floor_posts': execute_floor_posts(validated['floor_posts']),
        'fire_braces': execute_fire_braces(validated['fire_braces']),
        # 下階柱記号は直下階の柱を検索するため柱の描画後に配置する
        'column_marks': execute_column_marks(validated['column_marks']),
    }
    reorder_story_layers(validated['stories'])
    counters: dict[str, int] = {}
    counts['sheets'] = execute_sheets(
        validated['sheets'], validated['tags'], member_handles, counters,
        validated['legends'])
    counts['tags'] = counters.get('tags', 0)
    counts['legends'] = counters.get('legends', 0)
    return counts
