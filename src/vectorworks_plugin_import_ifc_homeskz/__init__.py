"""ホームズ君構造EX の IFC を VectorWorks にインポートするプラグインスクリプト。

処理は 2 フェーズに完全分離されている:

1. IFC 解析フェーズ (``ifc`` パッケージ, vs 非依存)
   ifcopenshell で IFC を解析し、JSON 直列化可能な命令セットを組み立てる。
2. 描画フェーズ (``vw`` パッケージ, vs 依存)
   命令セットに従って vs モジュールで実際の描画を行う。

命令セットのスキーマは ``document.py`` を参照。
"""
from __future__ import annotations

import json

from .document import validate_document
from .ifc import build_document, open_ifc
from .ifc.grid import TARGET_LAYER

__all__ = ['build_document', 'open_ifc', 'run', 'validate_document']


def run() -> None:
    # vs に依存するモジュールは VectorWorks 上での実行時のみ読み込む。
    # これにより ifc パッケージ(解析フェーズ)は通常の Python 環境でも利用できる。
    import vs

    from .vw import execute_document

    ok, filepath = vs.GetFileN('IFCファイルを選択してください', '', 'ifc')
    if not ok:
        vs.AlrtDialog('キャンセルされました。')
        return

    try:
        vs.Message('IFCデータを解析中...')

        # 解析前にスキーマ非適合のエンティティを除去して開く(基礎の取りこぼし防止)
        ifc_file = open_ifc(filepath)

        # フェーズ1: IFC 解析 → JSON 命令セット
        document = build_document(ifc_file)
        # JSON 文字列を経由して受け渡すことで、命令セットが常に
        # 直列化可能(= vs やifcopenshell のオブジェクトを含まない)ことを保証する
        document = json.loads(json.dumps(document))

        # フェーズ2: 命令セットに従って描画
        counts = execute_document(document)

        # 取り込み結果はモーダルアラートではなくステータスバーに表示する
        # (処理をブロックせず、ユーザーが続けて操作できるようにするため)
        vs.Message(
            f'読込完了: {counts["stories"]} 階のストーリ・ストーリレベル・デザインレイヤを設定し、'
            f'「{TARGET_LAYER}」レイヤに {counts["grids"]} 本の通り芯を配置しました。'
            f' 横架材天端レイヤに {counts["members"]} 本の構造材、'
            f'{counts["columns"]} 本の柱を配置しました。'
            f' 基礎に {counts["walls"]} 本の立上り(壁、{counts["wall_joins"]} 箇所を壁結合)、'
            f'{counts["slabs"]} 枚の底盤・地中梁(スラブ)、'
            f'{counts["anchor_bolts"]} 本のアンカーボルト(シンボル)、'
            f'{counts["floor_posts"]} 本の床束(シンボル)、'
            f'{counts["fire_braces"]} 本の火打(シンボル)を配置しました。'
            f' {counts["sheets"]} 枚のシートレイヤ(伏図)を作成し、'
            f'{counts["tags"]} 個の断面寸法データタグ、'
            f'{counts["column_marks"]} 個の下階柱記号、'
            f'{counts["legends"]} 個のグラフィック凡例を配置しました。'
        )

    except Exception as e:
        vs.ClrMessage()
        vs.AlrtDialog(f'エラーが発生しました: {str(e)}')
