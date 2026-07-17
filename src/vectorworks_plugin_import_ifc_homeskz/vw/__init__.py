"""フェーズ2: VectorWorks 描画。

JSON 命令セット(``document.py`` のスキーマ参照)に従って vs モジュールで
実際の描画を行う。このパッケージだけが vs に依存し、IFC や ifcopenshell の
知識は持たない。
"""
from __future__ import annotations

from typing import Any

from ..document import validate_document
from ..tracing import trace
from .anchor_bolt import execute_anchor_bolts
from .column import execute_columns
from .column_mark import execute_column_marks
from .fire_brace import execute_fire_braces
from .floor import execute_floors
from .floor_post import execute_floor_posts
from .footing import execute_slabs, execute_wall_joins, execute_walls
from .grid import execute_grids
from .joint import execute_joints
from .member import execute_members
from .rafter import execute_rafters
from .rebar import execute_rebars
from .roof import execute_roofs
from .sheet import execute_sheets
from .story import execute_stories, reorder_story_layers

__all__ = ['execute_anchor_bolts', 'execute_column_marks', 'execute_columns',
           'execute_document', 'execute_fire_braces', 'execute_floor_posts',
           'execute_floors', 'execute_grids', 'execute_joints',
           'execute_members', 'execute_rafters', 'execute_rebars',
           'execute_roofs', 'execute_sheets', 'execute_slabs',
           'execute_stories', 'execute_wall_joins', 'execute_walls',
           'reorder_story_layers']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 垂木 → 野地板 → 柱 → 立上り → 壁結合 → 底盤 → アンカーボルト → 床束 → 火打 → 仕口 → 下階柱記号 → レイヤ並べ替え → シートの順で描画する。

    構造材などの描画後に reorder_story_layers でデザインレイヤのスタック順を整える。
    通り芯レイヤ(共通)を最上段に積むため、その生成(通り芯描画)後に並べ替える
    必要がある。シート(ビューポート)はデザインレイヤを参照するため、それらの生成後
    (並べ替え後)に描画する。**並べ替えで床・野地板レイヤを最背面へ回した結果は、
    インポート直後のビューポート描画には反映されない**(レイヤパレット・ビューポートの
    プロパティ上は新しい順=床が最下段なのに描画だけ古い順)。VW 上の検証で、並べ替えは
    既存ビューポートを out-of-date にせず、``UpdateVP`` も ``ReDrawAll`` も
    ``Project 2D`` トグルによる強制再描画もスクリプト内では効かないことを確認した
    (手動「ビューポートを更新」またはファイルの開き直しでのみ反映される)。無駄な更新
    処理は行わず、この描画反映はユーザーの手動操作に委ねる(VW の制約として許容)。
    下階柱記号(柱束伏図記号 PIO)は配置後のリセットで直下階の柱を検索するため、柱の
    描画後に配置する。壁結合(execute_wall_joins)は立上りの壁ハンドルを参照するため、
    立上りをすべて配置した直後に実行する。

    Returns: {'stories', 'grids', 'members', 'rafters', 'roofs', 'columns',
        'walls', 'wall_joins', 'slabs', 'floors', 'rebars', 'anchor_bolts',
        'floor_posts', 'fire_braces', 'joints', 'column_marks', 'sheets',
        'tags', 'legends'}
        各命令の実行数。rafters は屋根版から導出した垂木(軸組)数、roofs は
        屋根版から導出した野地板(屋根オブジェクト)数、wall_joins は
        交差する立上りを結合した回数、slabs は底盤・地中梁数、floors は各階 FL
        レイヤに配置した床板(床)数、rebars は基礎に配置した配筋 PIO(鉄筋)数、
        floor_posts は大引下に配置した床束シンボル数、fire_braces は
        横架材レイヤに配置した火打シンボル数、joints は受ける材のある横架材端部に
        配置した仕口シンボル数、column_marks は下階柱レイヤに配置した
        柱束伏図記号 PIO 数、tags は伏図ビューポートに配置した断面寸法データタグ数、
        legends は基礎伏図に配置したグラフィック凡例数。
    """
    validated = validate_document(document)
    # 横架材のハンドルを記録し、断面寸法データタグ(シートフェーズ)の関連付けに使う
    member_handles: dict[int, Any] = {}
    # 立上りのハンドルを記録し、壁結合(execute_wall_joins)の関連付けに使う
    wall_handles: dict[int, Any] = {}
    # 各フェーズの前後にクラッシュ診断用トレース(tracing.py)を記録する。無言
    # クラッシュ時にログの最後の行の直後のフェーズがクラッシュ箇所になる。
    counts: dict[str, int] = {}
    trace('execute_stories start')
    counts['stories'] = execute_stories(validated['stories'])
    trace('execute_grids start')
    counts['grids'] = execute_grids(validated['grids'])
    trace('execute_members start')
    counts['members'] = execute_members(validated['members'], member_handles)
    # 垂木は屋根版から導出した軸組ツール(FramingMember)。母屋の直上の
    # n-垂木 レイヤに配置する(レイヤは story 命令が生成)。
    trace('execute_rafters start')
    counts['rafters'] = execute_rafters(validated['rafters'])
    # 野地板は屋根版から導出した屋根ツール(BeginRoof)。垂木の直上の
    # n-野地板 レイヤに配置する(レイヤは story 命令が生成)。
    trace('execute_roofs start')
    counts['roofs'] = execute_roofs(validated['roofs'])
    trace('execute_columns start')
    counts['columns'] = execute_columns(validated['columns'])
    trace('execute_walls start')
    counts['walls'] = execute_walls(validated['walls'], wall_handles)
    # 立上りをすべて配置した後に交差する壁同士を結合する
    trace('execute_wall_joins start')
    counts['wall_joins'] = execute_wall_joins(
        validated['wall_joins'], wall_handles)
    trace('execute_slabs start')
    counts['slabs'] = execute_slabs(validated['slabs'])
    # 床板(床ツール)は各階の FL レイヤに配置する
    trace('execute_floors start')
    counts['floors'] = execute_floors(validated['floors'])
    # 基礎の配筋(鉄筋 PIO)は立上り・底盤と同じレイヤに重ねる
    trace('execute_rebars start')
    counts['rebars'] = execute_rebars(validated['rebars'])
    trace('execute_anchor_bolts start')
    counts['anchor_bolts'] = execute_anchor_bolts(validated['anchor_bolts'])
    trace('execute_floor_posts start')
    counts['floor_posts'] = execute_floor_posts(validated['floor_posts'])
    trace('execute_fire_braces start')
    counts['fire_braces'] = execute_fire_braces(validated['fire_braces'])
    # 仕口(受ける材のある横架材端部のシンボル)は横架材レイヤに配置する
    trace('execute_joints start')
    counts['joints'] = execute_joints(validated['joints'])
    # 下階柱記号は直下階の柱を検索するため柱の描画後に配置する
    trace('execute_column_marks start')
    counts['column_marks'] = execute_column_marks(validated['column_marks'])
    # デザインレイヤのスタック順を整えてからシート(ビューポート)を描画する。
    # 並べ替えで床・野地板を最背面へ回した結果はインポート直後のビューポート描画には
    # 反映されず(手動更新/ファイル再オープンで反映)、スクリプト内での自動反映は
    # VW の制約上できないため、余計な更新処理は行わない(execute_document の
    # docstring 参照)。
    trace('reorder_story_layers start')
    reorder_story_layers(validated['stories'])
    counters: dict[str, int] = {}
    trace('execute_sheets start')
    counts['sheets'] = execute_sheets(
        validated['sheets'], validated['tags'], member_handles, counters,
        validated['legends'])
    counts['tags'] = counters.get('tags', 0)
    counts['legends'] = counters.get('legends', 0)
    trace('execute_document phases done')
    return counts
