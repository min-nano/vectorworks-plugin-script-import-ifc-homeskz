"""column_mark 命令の描画。下階柱記号(柱束伏図記号 PIO)を配置する。

各命令について、配置先レイヤ(``n-下階柱``)をアクティブにしてから
``vs.CreateCustomObject`` でカスタム PIO「柱束伏図記号」を挿入し、検索対象レイヤ・
クラス・記号サイズをパラメータ(レコードフィールド)に設定して ``vs.ResetObject``
でリセットする。PIO はリセット時に対象レイヤの柱(構造用途 4/5)を検索し各柱位置に
記号を描く(実際の記号描画は PIO 側=姉妹プロジェクト
vectorworks-plugin-column-under-mark が行う)。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
PIO プラグイン「柱束伏図記号」が VectorWorks に登録されていない場合、
``CreateCustomObject`` は NIL を返すためスキップする。
"""
from __future__ import annotations

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


def _format_size(size: float) -> str:
    """記号サイズ(mm)を PIO の MarkSize フィールドに渡す文字列に整形する。

    PIO 側は文字列を ``float`` で解釈するため、整数値は末尾の ``.0`` を付けない
    (300.0 → "300")。
    """
    return f'{size:g}'


def draw_column_mark(command: ColumnMarkCommand) -> bool:
    """column_mark 命令 1 件を柱束伏図記号 PIO として配置する。

    ``vs.CreateCustomObject`` で PIO を挿入点に作り、検索対象レイヤ・クラス・記号
    サイズをパラメータに設定して ``vs.ResetObject`` でリセットする。PIO が作れない
    (プラグイン未登録等で NIL)場合は False。
    """
    x, y = command['position']
    obj = vs.CreateCustomObject(_PLUGIN_NAME, (x, y), 0)
    if obj == vs.Handle(0):
        return False
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
