"""柱束伏図記号 PIO の命令(断面記号・伏図記号)の組み立て。vs 非依存。

姉妹プロジェクト vectorworks-plugin-column-under-mark のカスタム PIO
「柱束伏図記号」(指定レイヤ・クラスの構造用途 4/5 の構造材を検索し、記号スタイルに
従って各位置に記号を描くポイントオブジェクト)を配置する命令(column_mark 命令)を
組み立てる。柱・小屋束は span(``{from}to{to}-柱``)ごとのレイヤに配置される
(``ifc/column.py``)。**各 span レイヤは単一種別**(柱のみ=構造用途 4、または
小屋束のみ=構造用途 5)なので、柱用と小屋束用は別々の span レイヤ・別々のシンボルで
描き分けられる(PIO は変更せず、既存の単一 ``MarkSymbol`` を使う)。用途は 2 種類:

- **断面記号**(``style=断面``): 実在する span レイヤごとに 1 つ重ね、そのレイヤ自身を
  検索対象・配置先(``target_class`` は空=全クラス)にして、実断面に合わせた記号
  (柱×・小屋束/)を極細実線(``01作図-01線-02実線-01極細線``)で描く。各伏図はその
  span レイヤ(切断レベルを span が含む)を表示すると柱・小屋束の断面記号も併せて載る。
- **伏図記号**(``style=平面``): 各 span 柱レイヤの柱・小屋束を、その span の **``to``
  (span 上側の数値)** をプレフィックスにした専用レイヤ ``{to}-柱伏図記号`` に平面記号
  (シンボル)として描く。**シンボルはその span の種別で決める**(柱の span=構造用途 4
  なら ``柱伏図記号``、小屋束の span=構造用途 5 なら ``束伏図記号``)。同じ ``to`` の
  span(例 ``1to2.5`` と ``2to2.5``)は同じ ``{to}-柱伏図記号`` レイヤに載る(span
  ごとに PIO を 1 つ置き、検索対象は各 span レイヤ自身)。各伏図は切断位置の直下
  (``to`` < 切断)の伏図記号レイヤだけを表示するため、その伏図が対象とする横架材の
  下にある柱・小屋束が平面記号で示される(``ifc/sheet.py``)。

判断は柱の span レイヤ・構造用途(=column 命令)から決まり、IFC のジオメトリは参照
しない。
"""
from __future__ import annotations

from ..document import ColumnCommand, ColumnMarkCommand
from .column import STRUCTURAL_USE_KOYAZUKA, collect_column_spans
from .story import plan_mark_layer_name

# 記号の既定サイズ (mm)。柱束伏図記号 PIO の MarkSize に渡す。姉妹プロジェクトの
# 既定値 (core/mark.py の DEFAULT_MARK_SIZE=300mm) に合わせる。伏図記号でシンボルを
# 指定した場合はサイズに依存しない(シンボルをそのまま配置する)ため、断面記号の
# フォールバック用途が主。
DEFAULT_MARK_SIZE = 300.0
# 記号スタイル(柱束伏図記号 PIO の MarkStyle パラメータに渡す値)。姉妹プロジェクト
# vectorworks-plugin-column-under-mark の normalize_style が '断面'/'section' を断面記号、
# それ以外(空文字含む)を平面記号として解釈する。
MARK_STYLE_SECTION = '断面'  # 実断面に合わせた柱×・小屋束/
MARK_STYLE_PLAN = '平面'      # 伏図記号(シンボル)
# 断面記号(各 span 柱レイヤに重ねる柱束伏図記号 PIO)の作図クラス。極細の実線で
# 実断面の対角線を描く。
SECTION_MARK_CLASS = '01作図-01線-02実線-01極細線'
# 伏図記号(平面記号)の作図クラス。PIO 本体を作図する記号クラス。
PLAN_MARK_CLASS = '01作図-04記号-04構造-一般'
# 伏図記号で使うシンボル名。柱束伏図記号 PIO に MarkSymbol として渡す。span レイヤは
# 単一種別なので、その span の構造用途(柱=4/小屋束=5)でシンボルを選ぶ。VectorWorks
# 側で登録したシンボル名と一致させる必要がある。
SYMBOL_COLUMN = '柱伏図記号'    # 柱(管柱・通し柱)の span の伏図記号
SYMBOL_KOYAZUKA = '束伏図記号'  # 小屋束の span の伏図記号
# PIO の挿入点。記号は検索した柱のワールド位置に描かれ挿入点には依存しないため
# 原点でよい(座標はセンタリング済み)。
INSERTION_POINT: list[float] = [0.0, 0.0]


def _span_symbol(structural_use: str) -> str:
    """span の構造用途(柱=4/小屋束=5)から伏図記号のシンボル名を選ぶ。

    span レイヤは単一種別のため、その span を代表する構造用途で決まる。小屋束
    (``STRUCTURAL_USE_KOYAZUKA``=5)なら ``束伏図記号``、それ以外(柱=4)は
    ``柱伏図記号``。
    """
    if structural_use == STRUCTURAL_USE_KOYAZUKA:
        return SYMBOL_KOYAZUKA
    return SYMBOL_COLUMN


def build_column_mark_commands(
    columns: list[ColumnCommand],
) -> list[ColumnMarkCommand]:
    """column_mark 命令(断面記号・伏図記号)を span 柱レイヤごとに組み立てて返す。

    実在する span レイヤ(``collect_column_spans``、``(from, to)`` 昇順)ごとに:

    - **断面記号** 1 つ: 配置レイヤ・検索対象レイヤともにその span レイヤ、
      ``target_class`` は空(全クラス)、``style=断面``、作図クラス
      ``SECTION_MARK_CLASS``、``symbol`` は空。
    - **伏図記号** 1 つ: 配置レイヤは ``{to}-柱伏図記号``(``plan_mark_layer_name``)、
      検索対象レイヤはその span レイヤ、``target_class`` は空、``style=平面``、作図
      クラス ``PLAN_MARK_CLASS``、``symbol`` はその span の種別のシンボル(柱の span
      なら ``柱伏図記号``、小屋束の span なら ``束伏図記号``)。柱用と小屋束用は
      別々の span レイヤなので別々のオブジェクトとして配置される。

    span レイヤの種別(構造用途)は、そのレイヤの column 命令の ``structural_use``
    から取る(span レイヤは単一種別)。断面記号を先にすべて、続けて伏図記号をすべて
    並べる(命令の順序は描画に影響しないが、既存の断面記号の並びを保つ)。柱が
    無ければ空リストを返す。
    """
    # span レイヤ → 構造用途(単一種別のため最初に見つかった値でよい)。
    use_by_layer: dict[str, str] = {}
    for command in columns:
        use_by_layer.setdefault(command['layer'], command['structural_use'])

    spans = collect_column_spans(columns)
    section_marks: list[ColumnMarkCommand] = []
    plan_marks: list[ColumnMarkCommand] = []
    for _frm, to, layer in spans:
        section_marks.append({
            'layer': layer,
            'class': SECTION_MARK_CLASS,
            'target_layer': layer,
            'target_class': '',
            'size': DEFAULT_MARK_SIZE,
            'style': MARK_STYLE_SECTION,
            'symbol': '',
            'position': list(INSERTION_POINT),
        })
        symbol = _span_symbol(use_by_layer.get(layer, ''))
        plan_marks.append({
            'layer': plan_mark_layer_name(to),
            'class': PLAN_MARK_CLASS,
            'target_layer': layer,
            'target_class': '',
            'size': DEFAULT_MARK_SIZE,
            'style': MARK_STYLE_PLAN,
            'symbol': symbol,
            'position': list(INSERTION_POINT),
        })
    return section_marks + plan_marks
