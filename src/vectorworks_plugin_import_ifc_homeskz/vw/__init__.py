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
from .sheet import execute_sheets, refresh_viewports
from .story import execute_stories, reorder_story_layers

__all__ = ['execute_anchor_bolts', 'execute_column_marks', 'execute_columns',
           'execute_document', 'execute_fire_braces', 'execute_floor_posts',
           'execute_floors', 'execute_grids', 'execute_joints',
           'execute_members', 'execute_rafters', 'execute_rebars',
           'execute_roofs', 'execute_sheets', 'execute_slabs',
           'execute_stories', 'execute_wall_joins', 'execute_walls',
           'refresh_viewports', 'reorder_story_layers']


def execute_document(document: Any) -> dict[str, int]:
    """命令セットを検証し、ストーリ → 通り芯 → 構造材 → 垂木 → 野地板 → 柱 → 立上り → 壁結合 → 底盤 → アンカーボルト → 床束 → 火打 → 仕口 → 下階柱記号 → シート → レイヤ並べ替え → ビューポート更新の順で描画する。

    シート(ビューポート)はデザインレイヤを参照するため、レイヤ生成・構造材描画の
    後に描画する。そのうえで **シート描画 → reorder_story_layers(レイヤ並べ替え) →
    refresh_viewports(ビューポート更新)** の順にする。並べ替えは床・野地板レイヤを
    最背面へ回すが、VW の UpdateVP は「最新」とみなすビューポートを再描画しない
    (no-op)ため、ビューポートを並べ替えの後に作成すると並べ替えで out-of-date に
    ならず、床・野地板が前面のまま残る。ビューポートを先に作成し、並べ替えで
    out-of-date にしてから refresh_viewports で更新し直すことで新しい重ね順を反映
    させる。並べ替えは通り芯レイヤ(共通)を最上段に積むためその生成後に行う必要が
    あり、この順序を満たす。下階柱記号(柱束伏図記号 PIO)は配置後のリセットで
    直下階の柱を検索するため、柱の描画後に配置する。壁結合(execute_wall_joins)は
    立上りの壁ハンドルを参照するため、立上りをすべて配置した直後に実行する。

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
    # シート(ビューポート)は **デザインレイヤの並べ替え(reorder_story_layers)より
    # 前に** 作成する。並べ替えは床・野地板レイヤを最背面へ回すが、VW の UpdateVP は
    # 「最新」とみなすビューポートに対しては再描画しない(no-op)ため、ビューポートを
    # 並べ替えの後に作成すると並べ替えでは out-of-date にならず、床・野地板が前面の
    # まま残る。そこで **ビューポートを作成 → 並べ替え(既存ビューポートを out-of-date
    # にする) → refresh_viewports(UpdateVP で再描画)** の順にして、ユーザーの手動
    # 「ビューポートを更新」と同じ再描画を確実に効かせる。作成した全ビューポートの
    # ハンドルは viewport_handles に集める。
    viewport_handles: list[Any] = []
    counters: dict[str, int] = {}
    trace('execute_sheets start')
    counts['sheets'] = execute_sheets(
        validated['sheets'], validated['tags'], member_handles, counters,
        validated['legends'], viewport_handles)
    counts['tags'] = counters.get('tags', 0)
    counts['legends'] = counters.get('legends', 0)
    trace('reorder_story_layers start')
    reorder_story_layers(validated['stories'])
    # 並べ替えで out-of-date になったビューポートを更新し直し、床・野地板を最背面へ
    # 回した重ね順を反映させる(refresh_viewports の説明参照)。
    trace('refresh_viewports start')
    refresh_viewports(viewport_handles)
    trace('execute_document phases done')
    return counts
