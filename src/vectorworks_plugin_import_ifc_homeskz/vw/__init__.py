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
from .fire_brace import execute_fire_braces
from .footing import execute_slabs, execute_walls
from .grid import execute_grids
from .member import execute_members
from .sheet import execute_sheets
from .story import execute_stories, reorder_story_layers

__all__ = ['execute_anchor_bolts', 'execute_columns', 'execute_document',
           'execute_fire_braces', 'execute_grids', 'execute_members',
           'execute_sheets', 'execute_slabs', 'execute_stories',
           'execute_walls', 'reorder_story_layers']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 柱 → 立上り → 底盤 → アンカーボルト → 火打 → シートの順で描画する。

    構造材などの描画後に reorder_story_layers でデザインレイヤのスタック順を整える。
    通り芯レイヤ(共通)を最上段に積むため、その生成(通り芯描画)後に並べ替える
    必要がある。シート(ビューポート)はデザインレイヤを参照するため、それらの生成後
    (並べ替え後)に描画する。

    Returns: {'stories', 'grids', 'members', 'columns', 'walls', 'slabs',
        'anchor_bolts', 'fire_braces', 'sheets', 'tags'} 各命令の実行数。
        fire_braces は横架材レイヤに配置した火打シンボル数、tags は伏図
        ビューポートに配置した断面寸法データタグ数。
    """
    validated = validate_document(document)
    # 横架材のハンドルを記録し、断面寸法データタグ(シートフェーズ)の関連付けに使う
    member_handles: dict[int, Any] = {}
    counts = {
        'stories': execute_stories(validated['stories']),
        'grids': execute_grids(validated['grids']),
        'members': execute_members(validated['members'], member_handles),
        'columns': execute_columns(validated['columns']),
        'walls': execute_walls(validated['walls']),
        'slabs': execute_slabs(validated['slabs']),
        'anchor_bolts': execute_anchor_bolts(validated['anchor_bolts']),
        'fire_braces': execute_fire_braces(validated['fire_braces']),
    }
    reorder_story_layers(validated['stories'])
    counters: dict[str, int] = {}
    counts['sheets'] = execute_sheets(
        validated['sheets'], validated['tags'], member_handles, counters)
    counts['tags'] = counters.get('tags', 0)
    return counts
