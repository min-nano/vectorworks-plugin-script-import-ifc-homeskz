"""column 命令の描画。VectorWorks 木造BIM 柱・間柱ツールで柱を配置する。"""
from __future__ import annotations

import vs

from ..document import ColumnCommand, StoryBound

# 木造BIM 柱・間柱ツールの「ユニバーサル名」。CreateCustomObject / SetRField に
# はローカライズ名(柱・間柱)ではなくユニバーサル名を渡す必要がある。ローカライズ名
# を渡すと VW がその名前のパラメトリックオブジェクト型を新規定義しようとし、
# プラグインが登録済みの同名レコードフォーマット(柱・間柱)と衝突して
# 「同じ名前のレコードフォーマットがすでに存在しています」エラーになる。
# 構造材(StructuralMember)・通り芯(GridAxis)と同様にユニバーサル名で統一する。
PLUGIN_NAME = 'AAPillarS'

# SetObjectStoryBound の boundType: 0=LayerZ, 1=DefaultWallHeight, 2=Story
BOUND_TYPE_STORY = 2
# 上下端それぞれの story bound 識別子 (0=上端, 1=下端)
BOUND_ID_TOP = 0
BOUND_ID_BOTTOM = 1

# 伏図記号表示フィールド名・伏図レイヤフィールド名
FIELD_SHOW_PLAN_SYMBOL = 'isShowSecondary'
FIELD_PLAN_LAYER = 'upperLayerName'
# 柱頭金物・柱脚金物フィールド名(柱・間柱ツール AAPillarS の実フィールド名)。
# 仕様文字列(例: '(る)')は SetRField でそのまま書き込まれ、ツールの
# ドロップダウン候補に無いカスタム値でも登録不要でそのまま格納・表示される。
FIELD_TOP_HARDWARE = 'TopHard'
FIELD_BOTTOM_HARDWARE = 'BtmHard'
# 伏図記号表示を有効にするブール値
PLAN_SYMBOL_ON = 'True'

# 断面斜線クラス・丸記号クラス・伏図記号クラス（全種別共通）
CLASS_SECTION_MARK = '01作図-01線-02実線-01極細線'
CLASS_CIRCLE_MARK = '01作図-01線-02実線-03中線'
CLASS_SECONDARY = '01作図-01線-02実線-03中線'

# 柱種別ごとの本体クラス
_COLUMN_TYPE_CLASS: dict[str, str] = {
    '管柱': '04構造-02木造-03柱-02管柱',
    '通し柱': '04構造-02木造-03柱-01通し柱',
    '小屋束': '04構造-02木造-05小屋組-02小屋束',
}


def _set_story_bound(obj: object, bound_id: int, bound: StoryBound) -> None:
    """柱の上端/下端の高さ基準をストーリレベル基準で設定する。"""
    vs.SetObjectStoryBound(
        obj, bound_id, BOUND_TYPE_STORY,
        bound['story'], bound['level'], bound['offset'],
    )


def draw_column(command: ColumnCommand) -> None:
    """column 命令 1 件を柱・間柱ツールで描画する。

    柱はローカル原点 (0, 0) に生成し、CreateCustomObject 後に Move3D で
    XY 位置へ移動する。上下端の高さは固定値ではなく SetObjectStoryBound で
    ストーリレベル基準(下=横架材天端、上=上階の横架材天端 or 軒高)に
    バインドし、階高変更に追従させる(Z 方向の高さはこのバインドが決める)。
    伏図記号を表示し、伏図レイヤを当該階の柱(伏図)レイヤに設定する。
    柱頭・柱脚金物の仕様を TopHard / BtmHard フィールドに格納する。
    TopHard / BtmHard はツールが ResetObject 時に再計算する出力フィールドの
    ため、ResetObject の後に書き込む(前に設定すると空に上書きされる)。
    プラグインが利用できない場合は断面の矩形にフォールバックする。
    """
    x, y = command['position']
    w = int(round(command['width']))
    d = int(round(command['depth']))
    h = int(round(command['height']))

    obj = vs.CreateCustomObject(PLUGIN_NAME, 0, 0, 0)
    if obj != vs.Handle(0):
        # ローカル原点から実際の配置位置へ移動
        vs.ResetOrientation3D()
        vs.Move3D(x, y, command['elevation'])
        # 上下端の高さ基準をストーリレベルにバインド(Z 高さを決定する)
        _set_story_bound(obj, BOUND_ID_TOP, command['top_bound'])
        _set_story_bound(obj, BOUND_ID_BOTTOM, command['bottom_bound'])
        raw_column_type = command['column_type']
        if raw_column_type == 'STANDCOLUMN':
            column_type = '小屋束'
        elif raw_column_type in _COLUMN_TYPE_CLASS:
            column_type = raw_column_type
        else:
            column_type = '管柱'
        body_class = _COLUMN_TYPE_CLASS[column_type]
        vs.SetRField(obj, PLUGIN_NAME, 'Type', column_type)
        vs.SetRField(obj, PLUGIN_NAME, 'SecShape', '矩形')
        vs.SetRField(obj, PLUGIN_NAME, 'Width', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'Depth', str(d))
        vs.SetRField(obj, PLUGIN_NAME, 'Height', str(h))
        vs.SetRField(obj, PLUGIN_NAME, 'Rad', str(int(round(min(w, d) / 2))))
        vs.SetRField(obj, PLUGIN_NAME, 'Dia', str(w))
        # 本体クラス（2D・3D 共通、クラス属性を使用）
        vs.SetRField(obj, PLUGIN_NAME, 'Mclass', body_class)
        vs.SetRField(obj, PLUGIN_NAME, '2DShapeClass', body_class)
        vs.SetRField(obj, PLUGIN_NAME, 'use2DShapeClass', 'True')
        vs.SetRField(obj, PLUGIN_NAME, '3DShapeClass', body_class)
        vs.SetRField(obj, PLUGIN_NAME, 'use3DShapeClass', 'True')
        # 断面斜線クラス（クラス属性を使用）
        vs.SetRField(obj, PLUGIN_NAME, 'SectionMarkClass', CLASS_SECTION_MARK)
        vs.SetRField(obj, PLUGIN_NAME, 'useSectionMarkClass', 'True')
        # 丸記号クラス（クラス属性を使用）
        vs.SetRField(obj, PLUGIN_NAME, 'CircleMarkClass', CLASS_CIRCLE_MARK)
        vs.SetRField(obj, PLUGIN_NAME, 'useCircleMarkClass', 'True')
        vs.SetRField(obj, PLUGIN_NAME, 'Sclass', CLASS_CIRCLE_MARK)
        # 伏図記号クラス（クラス属性を使用）
        vs.SetRField(obj, PLUGIN_NAME, 'SecondaryClass', CLASS_SECONDARY)
        vs.SetRField(obj, PLUGIN_NAME, 'useSecondaryClass', 'True')
        # 伏図記号を表示し、伏図レイヤを当該階の柱(伏図)レイヤに設定する
        vs.SetRField(obj, PLUGIN_NAME, FIELD_SHOW_PLAN_SYMBOL, PLAN_SYMBOL_ON)
        vs.SetRField(obj, PLUGIN_NAME, FIELD_PLAN_LAYER, command['plan_layer'])
        vs.ResetObject(obj)
        # 柱頭・柱脚金物の仕様(該当金物が無ければ空文字)。
        # TopHard / BtmHard は柱・間柱ツールが ResetObject 時に継手条件から
        # 再計算する出力フィールドのため、ResetObject の前に設定すると上書きで
        # 消える(取り込んだ柱には継手ジオメトリが無いため空に再計算される)。
        # ResetObject の後に書き込み、以降は再リセットしないことで値を残す。
        vs.SetRField(obj, PLUGIN_NAME, FIELD_TOP_HARDWARE, command['top_hardware'])
        vs.SetRField(obj, PLUGIN_NAME, FIELD_BOTTOM_HARDWARE, command['bottom_hardware'])
    else:
        # フォールバック: 断面の矩形
        vs.Rect(x - w / 2, y + d / 2, x + w / 2, y - d / 2)
        vs.LNewObj()


def execute_columns(commands: list[ColumnCommand]) -> int:
    """column 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する。
    未生成 = ストーリ設定がスキップされた階であり、勝手にレイヤを作らない)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_column(command)
        count += 1

    return count
