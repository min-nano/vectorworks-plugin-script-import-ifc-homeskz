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

    n_stories = len(validated['stories'])
    n_grids = len(validated['grids'])
    n_members = len(validated['members'])
    n_columns = len(validated['columns'])
    total = max(n_stories + n_grids + n_members + n_columns, 1)

    # vs.Message() は描画中に呼ぶとプラグインオブジェクトのリセットを誘発するため、
    # 描画専用の ProgressDlg API を使う。
    vs.ProgressDlgOpen('IFC データを描画中...', False)
    try:
        stories = execute_stories(validated['stories'])
        vs.ProgressDlgSetMeter(int(n_stories * 100 / total))

        grids = execute_grids(validated['grids'])
        vs.ProgressDlgSetMeter(int((n_stories + n_grids) * 100 / total))

        members = execute_members(validated['members'])
        vs.ProgressDlgSetMeter(int((n_stories + n_grids + n_members) * 100 / total))

        columns = execute_columns(validated['columns'])
        vs.ProgressDlgSetMeter(100)
    finally:
        vs.ProgressDlgClose()

    return {'stories': stories, 'grids': grids, 'members': members, 'columns': columns}
