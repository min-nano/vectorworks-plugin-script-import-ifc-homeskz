"""フェーズ1: IFC 解析。

ifcopenshell で IFC ファイルを解析し、描画フェーズ(``vw`` パッケージ)への
入力となる JSON 直列化可能な命令セット(ドキュメント)を組み立てる。
このパッケージは vs(VectorWorks API)に一切依存しない。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import DOCUMENT_VERSION, Document
from .anchor_bolt import build_anchor_bolt_commands
from .column import build_column_commands
from .footing import (
    build_foundation_story_command,
    build_slab_commands,
    build_wall_commands,
)
from .grid import build_grid_commands
from .loader import open_ifc
from .member import build_member_commands
from .sheet import build_sheet_commands
from .story import build_story_commands

if TYPE_CHECKING:
    import ifcopenshell

__all__ = ['build_anchor_bolt_commands', 'build_column_commands',
           'build_document', 'build_foundation_story_command',
           'build_grid_commands', 'build_member_commands',
           'build_sheet_commands', 'build_slab_commands',
           'build_story_commands', 'build_wall_commands', 'open_ifc']


def build_document(ifc_file: ifcopenshell.file) -> Document:
    """IFC ファイルから JSON 命令セット(ドキュメント)を組み立てて返す。

    基礎ストーリ(``基礎``)が存在する場合は最下階として stories の先頭に置く
    (Elevation=0 で最下層になり、レイヤのスタック順でも最下段に積まれる)。
    """
    stories = build_story_commands(ifc_file)
    foundation_story = build_foundation_story_command(ifc_file)
    if foundation_story is not None:
        stories = [foundation_story, *stories]

    return {
        'version': DOCUMENT_VERSION,
        'stories': stories,
        'grids': build_grid_commands(ifc_file),
        'members': build_member_commands(ifc_file),
        'columns': build_column_commands(ifc_file),
        'walls': build_wall_commands(ifc_file),
        'slabs': build_slab_commands(ifc_file),
        'anchor_bolts': build_anchor_bolt_commands(ifc_file),
        'sheets': build_sheet_commands(ifc_file),
    }
