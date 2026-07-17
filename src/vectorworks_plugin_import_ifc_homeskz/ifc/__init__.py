"""フェーズ1: IFC 解析。

ifcopenshell で IFC ファイルを解析し、描画フェーズ(``vw`` パッケージ)への
入力となる JSON 直列化可能な命令セット(ドキュメント)を組み立てる。
このパッケージは vs(VectorWorks API)に一切依存しない。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import DOCUMENT_VERSION, Document
from .anchor_bolt import build_anchor_bolt_commands
from .column import build_column_commands, collect_column_layers_by_story
from .column_mark import build_column_mark_commands
from .fire_brace import build_fire_brace_commands
from .floor import build_floor_commands
from .floor_post import build_floor_post_commands
from .footing import (
    build_foundation_story_command,
    build_slab_commands,
    build_wall_commands,
    build_wall_join_commands,
)
from .grid import build_grid_commands
from .joint import build_joint_commands
from .loader import open_ifc
from .member import build_member_commands
from .rafter import build_rafter_commands
from .rebar import build_rebar_commands
from .roof import build_roof_commands
from .sheet import (
    build_floor_legend_commands,
    build_legend_commands,
    build_sheet_commands,
)
from .story import build_story_commands
from .tag import build_tag_commands

if TYPE_CHECKING:
    import ifcopenshell

__all__ = ['build_anchor_bolt_commands', 'build_column_commands',
           'build_column_mark_commands',
           'build_document', 'build_fire_brace_commands',
           'build_floor_commands',
           'build_floor_post_commands', 'build_foundation_story_command',
           'build_floor_legend_commands',
           'build_grid_commands', 'build_joint_commands',
           'build_legend_commands',
           'build_member_commands', 'build_rafter_commands',
           'build_rebar_commands', 'build_roof_commands',
           'build_sheet_commands', 'build_slab_commands',
           'build_story_commands', 'build_tag_commands', 'build_wall_commands',
           'build_wall_join_commands', 'open_ifc']


def build_document(ifc_file: ifcopenshell.file) -> Document:
    """IFC ファイルから JSON 命令セット(ドキュメント)を組み立てて返す。

    基礎ストーリ(``基礎``)が存在する場合は最下階として stories の先頭に置く
    (Elevation=0 で最下層になり、レイヤのスタック順でも最下段に積まれる)。
    """
    # 横架材命令は断面寸法データタグ・柱 span の to レベル判定(上階梁下端)にも
    # 使うため一度だけ組み立てる
    members = build_member_commands(ifc_file)
    # 柱命令は仕口(柱の側面に取り付く梁端部の判定)・span レイヤ生成(story)・伏図の
    # 表示レイヤ絞り込み(sheet)・断面記号(column_mark)にも使うため一度だけ組み立てる。
    # span の to レベル判定に上階梁下端が要るため members を渡す。
    columns = build_column_commands(ifc_file, members)
    # 柱の span レイヤ(``{from}to{to}-柱``)を base ストーリごとにまとめて story に渡す
    column_layers_by_story = collect_column_layers_by_story(columns)
    stories = build_story_commands(ifc_file, column_layers_by_story)
    foundation_story = build_foundation_story_command(ifc_file)
    if foundation_story is not None:
        stories = [foundation_story, *stories]

    # 立上り命令は壁結合(交点はインデックス参照)の組み立てにも使うため一度だけ組み立てる
    walls = build_wall_commands(ifc_file)
    # アンカーボルト命令は基礎伏図のグラフィック凡例(載せるシンボルの判定)にも
    # 使うため一度だけ組み立てる
    anchor_bolts = build_anchor_bolt_commands(ifc_file)

    return {
        'version': DOCUMENT_VERSION,
        'stories': stories,
        'grids': build_grid_commands(ifc_file),
        'members': members,
        # 垂木の差し込み(桁幅参照)に横架材命令を使うため一度だけ組み立てた
        # members を渡す(支持点の桁幅を軒桁から相互参照する)
        'rafters': build_rafter_commands(ifc_file, members),
        'roofs': build_roof_commands(ifc_file),
        'columns': columns,
        'walls': walls,
        'wall_joins': build_wall_join_commands(walls),
        'slabs': build_slab_commands(ifc_file, walls),
        'floors': build_floor_commands(ifc_file),
        'anchor_bolts': anchor_bolts,
        'floor_posts': build_floor_post_commands(ifc_file),
        'fire_braces': build_fire_brace_commands(ifc_file),
        # 仕口は横架材命令(食い込み調整済み)から受ける材のある端部を判定するため
        # 一度だけ組み立てた members を渡す。柱の側面に取り付く梁端部も仕口にするため
        # columns も渡す
        'joints': build_joint_commands(members, columns),
        # 伏図は各柱 span レイヤを切断レベルで絞って表示するため columns を渡す
        'sheets': build_sheet_commands(ifc_file, columns),
        'tags': build_tag_commands(members),
        # 断面記号は span 柱レイヤごとに置くため columns を渡す
        'column_marks': build_column_mark_commands(columns),
        # 基礎伏図(アンカーボルト)に続けて、各柱梁伏図・母屋伏図のグラフィック凡例
        # (床伏図凡例スタイル)を並べる。柱梁伏図・母屋伏図の番号を切断レベルで絞るため
        # columns を渡す。
        'legends': [
            *build_legend_commands(ifc_file, anchor_bolts),
            *build_floor_legend_commands(ifc_file, columns),
        ],
        'rebars': build_rebar_commands(ifc_file),
    }
