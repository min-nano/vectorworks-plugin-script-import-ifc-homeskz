"""フェーズ2: VectorWorks 描画。

JSON 命令セット(``document.py`` のスキーマ参照)に従って vs モジュールで
実際の描画を行う。このパッケージだけが vs に依存し、IFC や ifcopenshell の
知識は持たない。
"""
from __future__ import annotations

from typing import Any

from ..document import validate_document
from .column import execute_columns
from .grid import execute_grids
from .member import execute_members
from .story import execute_stories, reorder_story_layers

__all__ = ['execute_columns', 'execute_document', 'execute_grids',
           'execute_members', 'execute_stories', 'reorder_story_layers']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 柱の順で描画する。

    全描画後に reorder_story_layers でデザインレイヤのスタック順を整える。通り芯
    レイヤ(共通)を最上段に積むため、その生成(通り芯描画)後に並べ替える必要がある。

    Returns: {'stories': int, 'grids': int, 'members': int, 'columns': int} 各命令の実行数。
    """
    validated = validate_document(document)
    counts = {
        'stories': execute_stories(validated['stories']),
        'grids': execute_grids(validated['grids']),
        'members': execute_members(validated['members']),
        'columns': execute_columns(validated['columns']),
    }
    reorder_story_layers(validated['stories'])
    return counts
