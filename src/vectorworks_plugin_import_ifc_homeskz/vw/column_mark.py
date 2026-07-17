"""column_mark 命令の描画。柱束伏図記号 PIO(断面記号・伏図記号)を配置する。

各命令について、配置先レイヤをアクティブにしてから
``vs.CreateCustomObjectN`` でカスタム PIO「柱束伏図記号」を挿入し、PIO 本体
(=描かれる記号)のクラスを ``vs.SetClass`` で命令の ``class``
(断面記号=極細実線・伏図記号=記号クラス)に設定し、描画属性(線の太さ・色・
パターン・透明度等)を属性ごとの by-class 設定関数(``_set_all_attributes_by_class``)
ですべてクラス属性に従わせてから、検索対象レイヤ・クラス・記号サイズ・記号スタイル・
シンボル名(伏図記号のみ・単一の ``MarkSymbol``)をパラメータ(レコードフィールド)に
設定して ``vs.ResetObject`` でリセットする。PIO はリセット時に対象レイヤの柱
(構造用途 4/5)を検索し、記号スタイル(断面=実断面に合わせた柱×・小屋束/ / 平面=
柱×・小屋束○、またはシンボル指定時は指定シンボル)に従って各柱位置に記号を描く
(実際の記号描画は PIO 側=姉妹プロジェクト vectorworks-plugin-column-under-mark が行う)。
柱用と小屋束用は別々の span レイヤ・別々のシンボルの命令として渡される(span レイヤは
単一種別なので 1 レイヤ 1 シンボルで描き分けられ、PIO 本体の変更は不要)。

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
_PARAM_MARK_STYLE = 'MarkStyle'
# 伏図記号(平面記号)で配置するシンボル名を渡すパラメータ。span レイヤは単一種別
# なので、その span の種別のシンボル(柱=柱伏図記号/小屋束=束伏図記号)を渡す。
_PARAM_MARK_SYMBOL = 'MarkSymbol'
# 伏図記号(平面記号)の記号スタイル値。この値の命令の配置レイヤは通り芯(共通)の
# 直下に積む専用レイヤ(``{to}-柱伏図記号``)なので、``plan_mark_layers`` で列挙して
# レイヤ並べ替え(reorder_story_layers)に渡す。
_MARK_STYLE_PLAN = '平面'
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
    ダイアログを抑止)、検索対象レイヤ・クラス・記号サイズ・記号スタイルをパラメータ
    に設定して ``vs.ResetObject`` でリセットする。PIO が作れない(プラグイン未登録
    等で NIL)場合は False。
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
    vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MARK_STYLE, command['style'])
    # 伏図記号(平面記号)で配置するシンボル名(断面記号では空文字)。
    vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MARK_SYMBOL, command['symbol'])
    vs.ResetObject(obj)
    return True


def plan_mark_layers(commands: list[ColumnMarkCommand]) -> list[str]:
    """伏図記号(平面スタイル)命令の配置レイヤを重複なく登場順に返す。

    伏図記号レイヤ(``{to}-柱伏図記号``)は通り芯(``共通``)と同じくストーリに
    縛られない独立したデザインレイヤで、``execute_column_marks`` が生成する。
    ``execute_document`` はこの一覧を ``reorder_story_layers`` に渡し、``共通`` の
    直下(スタック上段)へ積む。
    """
    layers: list[str] = []
    for command in commands:
        if command['style'] == _MARK_STYLE_PLAN and command['layer'] not in layers:
            layers.append(command['layer'])
    return layers


def execute_column_marks(commands: list[ColumnMarkCommand]) -> int:
    """column_mark 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しなければ作成する(伏図記号レイヤ ``{to}-柱伏図記号`` は
    通り芯レイヤ ``共通`` と同じくストーリに縛られない独立レイヤで、story 命令では
    生成されないため。断面記号の配置先=span 柱レイヤは story 命令が既に生成済み)。
    作成後アクティブにして PIO を配置する。PIO が作れない命令は配置数に数えない。
    レイヤのスタック順(伏図記号レイヤを ``共通`` 直下に積む)は ``execute_document``
    が ``reorder_story_layers`` で整える。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            vs.CreateLayer(layer, 1)
        vs.Layer(layer)

        if draw_column_mark(command):
            count += 1

    return count
