"""section 命令の実行。既製の断面ビューポート(軸組図)を操作する。

断面ビューポートは VectorScript で新規作成できないため、あらかじめシートレイヤ ``A``
(タイトル 軸組図)に ``X1``..``X20`` / ``Y1``..``Y20`` の 40 枚を用意しておく。各
ビューポートには **断面指示線(``Section Line2`` PIO)** が対応し、指示線の
``Drawing Number`` / ``Drawing Title`` / 位置がビューポートを駆動する。既製の指示線は
**X通り=鉛直・Y通り=水平と方向別に正しい向きで用意されている**ため、本フェーズは
向きを変えず位置だけ操作する(回転はしない)。

本フェーズは section 命令に従って:

1. **``軸組図`` ビューポートスタイル**を編集し、全デザインレイヤを表示に設定し、
2. ``source_number``(``X{k}`` / ``Y{k}``)で既製の断面指示線を探し、
3. 切断位置(命令の ``line_start`` / ``line_end`` の中点)へ移動し、
4. ``Drawing Number`` / ``Drawing Title`` を切断位置に応じた通りの名前に変更し、
5. リンクするビューポートの図番・図面タイトルも合わせ、
6. 使わない既製の指示線とビューポートを削除し、
7. 残ったビューポートを更新してシートレイヤ ``A`` 上で重ならないように並べる。

既製の断面ビューポート(軸組図)はインポート前=デザインレイヤ生成前に、``軸組図``
という名前の**ビューポートスタイル**を関連付けて用意されている。軸組図は建物を切断した
断面図で全ての構造要素が写る必要があるため、生成したデザインレイヤを全て表示にしたい。
ビューポートスタイルはレイヤ・クラスの表示/非表示を持ち、**スタイルを編集すると、その
スタイルを使う全ビューポートに反映される**(By-Style の表示設定はスタイル側でのみ
編集できる)。そこで本フェーズは**個々のビューポート(インスタンス)ではなくスタイル
リソースそのものを編集**し、``軸組図`` スタイルで全デザインレイヤを表示に設定する
(``vs.GetObject('軸組図')`` でスタイルリソースのハンドルを取得し、そのハンドルに
``SetVPLayerVisibility`` で全デザインレイヤを表示に設定する)。デザインレイヤ生成後に
呼ばれるため、生成したレイヤも表示になる。

**ビューポートスタイルの取得・編集、断面指示線・ビューポートの検索/移動/改名/削除/
整列の各 vs 呼び出しは VectorWorks 上で最終確認する方針**(他要素と同じく、本モジュール
冒頭の名前付き定数に集約する)。指示線は長さも向きも変えず位置だけ操作する(既製が
方向別に正しい向きで用意されているため。要件どおり)。
"""
from __future__ import annotations

import re
from typing import Any

import vs

from ..document import SectionCommand

# 既製の断面ビューポートを載せたシートレイヤ番号(=レイヤ名)。
SECTION_SHEET_LAYER = 'A'

# 既製の断面ビューポートに関連付けられたビューポートスタイル名(ユーザーが VW 側で
# 用意する)。このスタイルを編集すると、スタイルを使う全ビューポートに反映される。
# vs.GetObject(名前) でスタイルリソースのハンドルを取得できる。VW 側の登録名と一致
# させる必要がある。
SECTION_VIEWPORT_STYLE = '軸組図'

# 断面指示線の PIO 名とフィールド名(実オブジェクトのスクリプト書き出しで確認済み)。
_PIO_SECTION_LINE = 'Section Line2'
_F_DRAWING_NUMBER = 'Drawing Number'
_F_DRAWING_TITLE = 'Drawing Title'
_F_LINKED_TO = 'Linked To'

# ビューポートのオブジェクト変数 selector(vw/sheet.py と同じ)。
_OV_VP_DRAWING_TITLE = 1032   # 図面タイトル
_OV_VP_DRAWING_NUMBER = 1033  # 図番

# ビューポートのレイヤ表示種別(SetVPLayerVisibility): 0=表示, 1=非表示, 2=グレー
# (vw/sheet.py と同じ)。軸組図(断面)は全ての構造要素を写すため全レイヤを表示にする。
_VP_LAYER_VISIBLE = 0

# 既製ビューポートの図番パターン(X1..X20 / Y1..Y20)。使わずに残ったものだけを削除
# 対象にし、それ以外の断面指示線(手置き等)には触れない。
_PREMADE_NUMBER_RE = re.compile(r'^[XY]\d+$')

# シートレイヤ A 上でビューポートを並べるレイアウト。左上を基準に、1 行 _COLUMNS 枚ずつ、
# ビューポート間に _GAP の余白を空けて重ならないように詰める(用紙上・mm)。VW 上で
# 最終調整する。
_ARRANGE_ORIGIN = (0.0, 0.0)
_ARRANGE_COLUMNS = 5
_ARRANGE_GAP = 300.0


def _index_section_lines() -> dict[str, Any]:
    """全レイヤを走査し、断面指示線を ``Drawing Number`` → ハンドルの辞書で返す。

    各オブジェクトに ``Section Line2`` レコードの ``Drawing Number`` を問い合わせ、
    非空のものだけを集める(断面指示線でないオブジェクトは空文字を返すため除外される)。
    """
    index: dict[str, Any] = {}
    layer = vs.FLayer()
    while layer != vs.Handle(0):
        obj = vs.FInLayer(layer)
        while obj != vs.Handle(0):
            number = vs.GetRField(obj, _PIO_SECTION_LINE, _F_DRAWING_NUMBER)
            if number:
                index[number] = obj
            obj = vs.NextObj(obj)
        layer = vs.NextLayer(layer)
    return index


def _center(handle: Any) -> tuple[float, float]:
    """オブジェクトのバウンディングボックス中心 (x, y) を返す。"""
    p1, p2 = vs.GetBBox(handle)
    return ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)


def _viewport_for(section_line: Any) -> Any:
    """断面指示線にリンクするビューポートのハンドルを返す(無ければ None)。

    指示線の ``Linked To``(例 ``Y1/A``)がビューポートの名前になっているため、
    ``vs.GetObject`` で引く。
    """
    linked = vs.GetRField(section_line, _PIO_SECTION_LINE, _F_LINKED_TO)
    if not linked:
        return None
    vp = vs.GetObject(linked)
    return vp if vp != vs.Handle(0) else None


def _place_section_line(handle: Any, command: SectionCommand) -> None:
    """断面指示線を切断位置へ移動し、図番・タイトルを変更する。

    既製の指示線は X通り=鉛直・Y通り=水平と方向別に正しい向きで用意されているため、
    向きは変えず、命令の ``line_start`` / ``line_end`` の中点へ中心を移動するだけにする
    (長さも向きも変えない)。
    """
    center = _center(handle)
    start, end = command['line_start'], command['line_end']
    mid_x = (start[0] + end[0]) / 2.0
    mid_y = (start[1] + end[1]) / 2.0
    vs.HMove(handle, mid_x - center[0], mid_y - center[1])
    vs.SetRField(handle, _PIO_SECTION_LINE, _F_DRAWING_NUMBER,
                 command['drawing_number'])
    vs.SetRField(handle, _PIO_SECTION_LINE, _F_DRAWING_TITLE,
                 command['drawing_title'])
    vs.ResetObject(handle)


def apply_all_layers_to_section_style() -> bool:
    """``軸組図`` ビューポートスタイルを編集し、全デザインレイヤを表示に設定する。

    既製の断面ビューポート(軸組図)には ``軸組図`` という名前のビューポートスタイルが
    関連付けられている。ビューポートスタイルはレイヤの表示/非表示を持ち、**スタイルを
    編集するとそのスタイルを使う全ビューポートに反映される**(By-Style の表示設定は
    スタイル側でのみ編集できる)。そこで個々のビューポートではなく**スタイルリソース
    そのもの**を編集する: ``vs.GetObject('軸組図')`` でスタイルリソースのハンドルを取得
    し、全デザインレイヤ(``FLayer`` → ``NextLayer``)を辿って ``SetVPLayerVisibility``
    でスタイルハンドルに表示を設定する(``SetVPLayerVisibility`` はデザインレイヤのみが
    対象で、シートレイヤに渡しても無害)。デザインレイヤ生成後に呼ばれるため、生成した
    レイヤも表示になる。スタイルが見つからない(``軸組図`` スタイルが未用意)場合は
    何もせず False を返す。編集できたら True を返す。

    **スタイルリソースの取得・編集の各 vs 呼び出しは VectorWorks 上で最終確認する
    方針**(他要素と同じく、本モジュール冒頭の名前付き定数に集約する)。
    """
    style_h = vs.GetObject(SECTION_VIEWPORT_STYLE)
    if style_h == vs.Handle(0):
        return False
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        vs.SetVPLayerVisibility(style_h, layer_h, _VP_LAYER_VISIBLE)
        layer_h = vs.NextLayer(layer_h)
    return True


def _arrange_viewports(viewports: list[Any]) -> None:
    """ビューポートを更新し、シートレイヤ上で重ならないように格子状に並べる。

    左上 (``_ARRANGE_ORIGIN``) から 1 行 ``_ARRANGE_COLUMNS`` 枚ずつ、各ビューポートの
    実サイズ(``GetBBox``)に ``_ARRANGE_GAP`` の余白を足して詰める。
    """
    origin_x, origin_y = _ARRANGE_ORIGIN
    cur_x, cur_y = origin_x, origin_y
    row_height = 0.0
    col = 0
    for vp in viewports:
        vs.UpdateVP(vp)
        p1, p2 = vs.GetBBox(vp)
        left, top = p1[0], p1[1]
        right, bottom = p2[0], p2[1]
        width, height = right - left, top - bottom
        vs.HMove(vp, cur_x - left, cur_y - top)
        cur_x += width + _ARRANGE_GAP
        row_height = max(row_height, height)
        col += 1
        if col >= _ARRANGE_COLUMNS:
            col = 0
            cur_x = origin_x
            cur_y -= row_height + _ARRANGE_GAP
            row_height = 0.0


def execute_sections(commands: list[SectionCommand]) -> int:
    """section 命令のリストを実行し、配置(流用)した断面ビューポート数を返す。

    まず ``軸組図`` ビューポートスタイルを編集して全デザインレイヤを表示に設定する
    (軸組図=断面は全ての構造要素を写すため。スタイル編集はそのスタイルを使う全
    ビューポートに反映される)。続いて既製の断面指示線を図番で探して切断位置へ移動・
    改名し、リンクするビューポートの図番・タイトルも合わせる。使わなかった既製の
    指示線・ビューポートを削除し、残ったビューポートを更新してシートレイヤ上で
    重ならないように並べる。
    """
    # 個々のビューポートではなく ``軸組図`` ビューポートスタイルそのものを編集し、
    # 全デザインレイヤを表示にする(スタイルを使う全ビューポートに反映される)。
    # デザインレイヤ生成後に呼ばれるため、生成したレイヤも表示になる。
    apply_all_layers_to_section_style()
    if not commands:
        return 0
    index = _index_section_lines()
    used_numbers: set[str] = set()
    used_viewports: list[Any] = []
    placed = 0
    for command in commands:
        src = index.get(command['source_number'])
        if src is None:
            continue
        # リンク先ビューポートは改名前に取得する(Linked To は改名で変わらない)
        vp = _viewport_for(src)
        _place_section_line(src, command)
        if vp is not None:
            vs.SetObjectVariableString(vp, _OV_VP_DRAWING_TITLE,
                                       command['drawing_title'])
            vs.SetObjectVariableString(vp, _OV_VP_DRAWING_NUMBER,
                                       command['drawing_number'])
            used_viewports.append(vp)
        used_numbers.add(command['source_number'])
        placed += 1
    # 使わなかった既製の断面指示線とビューポートを削除する(手置きの指示線には触れない)
    for number, obj in index.items():
        if number in used_numbers or not _PREMADE_NUMBER_RE.match(number):
            continue
        vp = _viewport_for(obj)
        if vp is not None:
            vs.DelObject(vp)
        vs.DelObject(obj)
    # 残ったビューポートを更新してシートレイヤ上で重ならないように並べる
    _arrange_viewports(used_viewports)
    return placed
