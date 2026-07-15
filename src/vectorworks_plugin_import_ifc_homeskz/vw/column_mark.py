"""column_mark 命令の描画。下階柱記号(柱束伏図記号 PIO)を配置する。

各命令について、配置先レイヤ(``n-下階柱``)をアクティブにしてから
``vs.CreateCustomObjectN`` でカスタム PIO「柱束伏図記号」を挿入し、PIO 本体
(=描かれる記号)のクラスを ``vs.SetClass`` で命令の ``class``
(柱・束の伏図記号の作図クラス)に設定し、描画属性(線の太さ・色・パターン・
透明度等)を属性ごとの by-class 設定関数(``_set_all_attributes_by_class``)で
すべてクラス属性に従わせてから、検索対象レイヤ・クラス・記号サイズをパラメータ
(レコードフィールド)に設定して ``vs.ResetObject`` でリセットする。PIO はリセット時に対象レイヤの柱
(構造用途 4/5)を検索し各柱位置に記号を描く(実際の記号描画は PIO 側=姉妹
プロジェクト vectorworks-plugin-column-under-mark が行う)。

``CreateCustomObject`` ではなく ``CreateCustomObjectN`` を使い ``showPref=False``
を渡すのは、**IFC インポート中に PIO の「オブジェクトの設定」ダイアログが
開いて手動入力を求められるのを防ぐため**。ユーザーが VectorWorks に登録した
「柱束伏図記号」ポイントオブジェクトは「図形の作成時に設定ダイアログを表示」
する設定になっており、``CreateCustomObject`` はこのプラグイン設定に従って
毎回ダイアログを表示してしまう(検索対象レイヤ・クラス・記号サイズはこの後
``SetRField`` で自動設定するため、手動入力は不要)。``CreateCustomObjectN`` の
``showPref`` 引数(=オブジェクトプロパティダイアログの表示)を ``False`` にする
ことでプラグイン設定によらずダイアログを抑止する。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
PIO プラグイン「柱束伏図記号」が VectorWorks に登録されていない場合、
``CreateCustomObjectN`` は NIL を返すためスキップする。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import ColumnMarkCommand

# 柱束伏図記号プラグインオブジェクト(下階柱記号)の内部プラグイン名・レコード名。
# VectorWorks 側でこの名前のポイントオブジェクトプラグインを登録すること。
_PLUGIN_NAME = '柱束伏図記号'
# PIO のパラメータ(レコードフィールド)名。姉妹プロジェクト
# vectorworks-plugin-column-under-mark の __init__.py の定数と一致させる。
_PARAM_TARGET_LAYER = 'TargetLayer'
_PARAM_TARGET_CLASS = 'TargetClass'
_PARAM_MARK_SIZE = 'MarkSize'
# CreateCustomObjectN の showPref 引数(オブジェクトプロパティダイアログの表示)。
# インポート中にダイアログで手動入力を求められないよう常に非表示にする。
_SHOW_PREF_DIALOG = False


def _format_size(size: float) -> str:
    """記号サイズ(mm)を PIO の MarkSize フィールドに渡す文字列に整形する。

    PIO 側は文字列を ``float`` で解釈するため、整数値は末尾の ``.0`` を付けない
    (300.0 → "300")。
    """
    return f'{size:g}'


def _set_all_attributes_by_class(obj: Any) -> None:
    """オブジェクトの描画属性(太さ・色・パターン・透明度等)をすべてクラス属性に従わせる。

    ``SetClass`` はクラスを割り当てるだけで、各描画属性は by-instance の既定値の
    まま残る。VectorWorks には属性一括の「すべてクラス属性に」関数が無いため、
    属性ごとの by-class 設定関数(いずれも対象ハンドルを取る)を個別に呼ぶ:

    - 線色 → ``SetPenColorByClass`` / 塗色 → ``SetFillColorByClass``
    - 線の太さ → ``SetLWByClass`` / 線種 → ``SetLSByClass``
    - 塗りパターン → ``SetFPatByClass`` / マーカー(矢印) → ``SetMarkerByClass``
    - 透明度 → ``SetOpacityByClass``

    リセットで再描画される記号は PIO の属性を継承するため、``ResetObject`` より前に
    設定する。
    """
    vs.SetPenColorByClass(obj)
    vs.SetFillColorByClass(obj)
    vs.SetLWByClass(obj)
    vs.SetLSByClass(obj)
    vs.SetFPatByClass(obj)
    vs.SetMarkerByClass(obj)
    vs.SetOpacityByClass(obj)


def draw_column_mark(command: ColumnMarkCommand) -> bool:
    """column_mark 命令 1 件を柱束伏図記号 PIO として配置する。

    ``vs.CreateCustomObjectN`` で PIO を挿入点に作り(``showPref=False`` で設定
    ダイアログを抑止)、検索対象レイヤ・クラス・記号サイズをパラメータに設定して
    ``vs.ResetObject`` でリセットする。PIO が作れない(プラグイン未登録等で NIL)
    場合は False。
    """
    x, y = command['position']
    obj = vs.CreateCustomObjectN(_PLUGIN_NAME, (x, y), 0, _SHOW_PREF_DIALOG)
    if obj == vs.Handle(0):
        return False
    vs.SetClass(obj, command['class'])
    _set_all_attributes_by_class(obj)
    vs.SetRField(obj, _PLUGIN_NAME, _PARAM_TARGET_LAYER, command['target_layer'])
    vs.SetRField(obj, _PLUGIN_NAME, _PARAM_TARGET_CLASS, command['target_class'])
    vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MARK_SIZE, _format_size(command['size']))
    vs.ResetObject(obj)
    return True


def execute_column_marks(commands: list[ColumnMarkCommand]) -> int:
    """column_mark 命令のリストを描画し、配置数を返す。

    配置先レイヤ(``n-下階柱``)が存在しない命令はスキップする(レイヤは story 命令が
    生成する)。PIO が作れない命令も配置数に数えない。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        if draw_column_mark(command):
            count += 1

    return count
