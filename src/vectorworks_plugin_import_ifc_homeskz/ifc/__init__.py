"""フェーズ1: IFC 解析。

ifcopenshell で IFC ファイルを解析し、描画フェーズ（``vw`` パッケージ）への
入力となる JSON 直列化可能な命令セット（ドキュメント）を組み立てる。
このパッケージは vs（VectorWorks API）に一切依存しない。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import DOCUMENT_VERSION, Document
from .grid import build_grid_commands
from .member import build_member_commands
from .story import build_story_commands

if TYPE_CHECKING:
    import ifcopenshell

__all__ = ['build_document', 'build_grid_commands', 'build_member_commands',
           'build_story_commands']


def build_document(ifc_file: ifcopenshell.file) -> Document:
    """IFC ファイルから JSON 命令セット（ドキュメント）を組み立てて返す。"""
    return {
        'version': DOCUMENT_VERSION,
        'stories': build_story_commands(ifc_file),
        'grids': build_grid_commands(ifc_file),
        'members': build_member_commands(ifc_file),
    }
