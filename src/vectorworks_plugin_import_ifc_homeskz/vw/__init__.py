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
from .story import execute_stories

__all__ = ['execute_columns', 'execute_document', 'execute_grids',
           'execute_members', 'execute_stories']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 柱の順で描画する。

    Returns: {'stories': int, 'grids': int, 'members': int, 'columns': int} 各命令の実行数。
    """
    import vs

    validated = validate_document(document)

    vs.Message(f'ストーリ・レイヤを生成中... (1/4, 計 {len(validated["stories"])} 階)')
    stories = execute_stories(validated['stories'])

    vs.Message(f'通り芯を配置中... (2/4, 計 {len(validated["grids"])} 本)')
    grids = execute_grids(validated['grids'])

    vs.Message(f'横架材を配置中... (3/4, 計 {len(validated["members"])} 本)')
    members = execute_members(validated['members'])

    vs.Message(f'柱を配置中... (4/4, 計 {len(validated["columns"])} 本)')
    columns = execute_columns(validated['columns'])

    return {'stories': stories, 'grids': grids, 'members': members, 'columns': columns}
