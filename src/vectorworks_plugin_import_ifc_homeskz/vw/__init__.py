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

    # vs.Message() は描画中に呼ぶとプラグインオブジェクトのリセットを誘発するため、
    # 描画専用の ProgressDlg API を使う。
    # ProgressDlgYield() がアイテムごとに UI を更新する（バーを進める + 再描画）。
    # ProgressDlgStart(pct, loopCount) でフェーズごとの割合を定義し、
    # ProgressDlgEnd() でそのフェーズの終端まで一気に進める。
    vs.ProgressDlgOpen('IFC インポート', False)
    try:
        vs.ProgressDlgSetTopMsg(f'ストーリ・レイヤを生成中... (計 {n_stories} 階)')
        vs.ProgressDlgStart(25.0, max(n_stories, 1))
        stories = execute_stories(validated['stories'], vs.ProgressDlgYield)
        vs.ProgressDlgEnd()

        vs.ProgressDlgSetTopMsg(f'通り芯を配置中... (計 {n_grids} 本)')
        vs.ProgressDlgStart(25.0, max(n_grids, 1))
        grids = execute_grids(validated['grids'], vs.ProgressDlgYield)
        vs.ProgressDlgEnd()

        vs.ProgressDlgSetTopMsg(f'横架材を配置中... (計 {n_members} 本)')
        vs.ProgressDlgStart(25.0, max(n_members, 1))
        members = execute_members(validated['members'], vs.ProgressDlgYield)
        vs.ProgressDlgEnd()

        vs.ProgressDlgSetTopMsg(f'柱を配置中... (計 {n_columns} 本)')
        vs.ProgressDlgStart(25.0, max(n_columns, 1))
        columns = execute_columns(validated['columns'], vs.ProgressDlgYield)
        vs.ProgressDlgEnd()
    finally:
        vs.ProgressDlgClose()

    return {'stories': stories, 'grids': grids, 'members': members, 'columns': columns}
