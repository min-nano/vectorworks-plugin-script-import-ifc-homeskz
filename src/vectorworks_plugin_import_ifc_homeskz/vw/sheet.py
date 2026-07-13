"""sheet 命令の実行。シートレイヤとビューポートを生成する。

各 sheet 命令について、シートレイヤ(プレゼンテーションレイヤ)を作成し、その上に
指定したデザインレイヤ群を表示するビューポートを 1 つ配置する。ビューポートには
命令の ``layers`` に挙げたデザインレイヤだけを表示し、それ以外のデザインレイヤは
非表示にする。クラスは伏図に必要な要素が欠けないよう全クラスを表示にする。
ビューポートの縮尺は表示するデザインレイヤの縮尺に合わせる。

シートレイヤ番号は VectorWorks ではシートレイヤ(=レイヤ)の名前がそのまま担うため、
``vs.CreateLayer`` に番号を渡してレイヤ名=シートレイヤ番号にする。シートレイヤタイトル・
ビューポートの図面タイトル・図番は オブジェクト変数(``SetObjectVariableString`` の
selector)で設定する。selector 値は VectorWorks 公式のオブジェクト変数一覧に基づく
(``document.py`` のスキーマ参照)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SheetCommand, TagCommand, ViewportCommand

# データタグの内部プラグイン名(VW の Data Tag ツール)。VW で最終確認する。
_DATA_TAG_PLUGIN = 'Data Tag'

# データタグの「引出線を表示」パラメータ(オブジェクト情報パレットのチェックボックス)。
# 既定 ON で、部材に接して置いても引出線が描かれてしまうため per-instance で OFF に
# する。フィールド名 'Use Leader'・Boolean 値 'False' は VW が描画したデータタグの
# VectorScript エクスポートで確認済み。
_LEADER_FIELD = 'Use Leader'
_LEADER_OFF = 'False'

# レイヤ種別(vs.CreateLayer): 1=デザインレイヤ, 2=プレゼンテーション(シート)レイヤ
_SHEET_LAYER_TYPE = 2

# シートレイヤのオブジェクト変数 selector(SetObjectVariableString)。
# シートレイヤ番号はレイヤ名が担う(CreateLayer に番号を渡す)ため selector は無い。
_OV_SHEET_TITLE = 159   # シートレイヤタイトル

# ビューポートのオブジェクト変数 selector(SetObjectVariableString)
_OV_VP_DRAWING_TITLE = 1032   # 図面タイトル
_OV_VP_DRAWING_NUMBER = 1033  # 図番
# ビューポートの縮尺 selector(SetObjectVariableReal)。値はデザインレイヤと同じく
# 1:N の N(GetLScale が返す縮尺係数)。
_OV_VP_SCALE = 1003

# ビューポートのレイヤ表示種別(SetVPLayerVisibility): 0=表示, 1=非表示, 2=グレー
# 対象外レイヤは 2(グレー)だとグレー表示で残ってしまうため 1(非表示)で完全に隠す。
_VP_LAYER_VISIBLE = 0
_VP_LAYER_HIDDEN = 1

# ビューポートのクラス表示種別(SetVPClassVisibility): 0=表示, 1=非表示, 2=グレー
_VP_CLASS_VISIBLE = 0


def configure_viewport_layers(
    viewport: Any, target_layers: list[str], sheet_layer: Any,
) -> None:
    """ビューポートで target_layers だけを表示し、他のデザインレイヤを非表示にする。

    全デザインレイヤ(FLayer→NextLayer)を辿っていったん非表示にし(ビューポートの
    親であるシートレイヤ自身は除く)、そのあと target_layers を名前で引いて表示に
    戻す。これにより ``layers`` に挙げたレイヤだけが表示される。
    """
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        if layer_h != sheet_layer:
            vs.SetVPLayerVisibility(viewport, layer_h, _VP_LAYER_HIDDEN)
        layer_h = vs.NextLayer(layer_h)
    for name in target_layers:
        target_h = vs.GetLayerByName(name)
        if target_h != vs.Handle(0):
            vs.SetVPLayerVisibility(viewport, target_h, _VP_LAYER_VISIBLE)


def configure_viewport_classes(viewport: Any) -> None:
    """ビューポートで全クラスを表示にする。

    ビューポートは既定で一部クラスが非表示になることがあるため、ドキュメントの
    全クラス(``ClassNum``/``ClassList``)を辿って表示に設定する。表示レイヤは
    ``configure_viewport_layers`` で絞り込むが、クラスは伏図に必要な要素が欠けない
    よう全て表示する。
    """
    for i in range(1, vs.ClassNum() + 1):
        vs.SetVPClassVisibility(viewport, vs.ClassList(i), _VP_CLASS_VISIBLE)


def configure_viewport_scale(viewport: Any, target_layers: list[str]) -> None:
    """ビューポートの縮尺を表示するデザインレイヤの縮尺に合わせる。

    ``target_layers`` のうち最初に見つかったデザインレイヤの縮尺(``GetLScale``)を
    そのままビューポートの縮尺に設定する(伏図では表示レイヤの縮尺は揃っている)。
    レイヤが 1 つも見つからなければ何もしない(既定縮尺のまま)。
    """
    for name in target_layers:
        layer_h = vs.GetLayerByName(name)
        if layer_h != vs.Handle(0):
            vs.SetObjectVariableReal(viewport, _OV_VP_SCALE, vs.GetLScale(layer_h))
            return


def draw_viewport(
    viewport: ViewportCommand, sheet_layer: Any,
) -> Any:
    """シートレイヤ上にビューポートを 1 つ生成し、生成したビューポートハンドルを返す。

    ``vs.CreateVP`` でシートレイヤ上にビューポートを作り、表示レイヤを絞り込み、
    図面タイトル・図番を設定してから ``vs.UpdateVP`` で描画を更新する。
    ビューポートが生成できない場合は None を返す。
    """
    obj = vs.CreateVP(sheet_layer)
    if obj == vs.Handle(0):
        return None
    vs.SetName(obj, viewport['drawing_title'])
    configure_viewport_layers(obj, viewport['layers'], sheet_layer)
    configure_viewport_classes(obj)
    configure_viewport_scale(obj, viewport['layers'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_TITLE, viewport['drawing_title'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_NUMBER, viewport['drawing_number'])
    vs.UpdateVP(obj)
    return obj


def draw_sheet(command: SheetCommand) -> Any:
    """sheet 命令 1 件をシートレイヤ + ビューポートとして描画し、ビューポートを返す。

    シートレイヤ(プレゼンテーションレイヤ)を **シートレイヤ番号を名前として**
    作成し(VW ではシートレイヤ番号はレイヤ名が担う)、シートレイヤタイトルを
    設定してから、その上にビューポートを配置する。同じ番号のシートレイヤが既にある
    場合は再利用する。ビューポート(またはシートレイヤ)が作れない場合は None を返す。
    """
    number = command['number']
    sheet_layer = vs.GetObject(number)
    if sheet_layer == vs.Handle(0):
        sheet_layer = vs.CreateLayer(number, _SHEET_LAYER_TYPE)
    if sheet_layer == vs.Handle(0):
        return None
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_TITLE, command['title'])
    return draw_viewport(command['viewport'], sheet_layer)


def draw_tag(tag: TagCommand, member_handle: Any, viewport: Any) -> bool:
    """tag 命令 1 件をビューポート注釈のデータタグとして描画する。

    ``vs.CreateCustomObject`` でデータタグ(``断面寸法`` スタイル)を挿入位置・
    軸方向の角度で作り、対象の横架材(``member_handle``)に関連付けて
    ビューポートの注釈に追加する。関連付け対象が無い(横架材がフォールバック
    描画等でハンドルを持たない)場合は関連付けを省く。タグが作れなければ False。

    **「引出線を表示」の OFF は関連付け・タグ更新の後に最後に設定する。**
    スタイル適用・関連付け・``DT_UpdateTaggedTags`` はタグを再生成してスタイルの
    引出線設定(既定 ON)を引き直すため、途中で OFF にしても上書きされてしまう。
    すべての再生成が終わった後に「引出線を表示」を OFF にして ``ResetObject`` で
    反映することで、引出線を確実に消す。
    """
    x, y = tag['position']
    obj = vs.CreateCustomObject(_DATA_TAG_PLUGIN, (x, y), tag['angle'])
    if obj == vs.Handle(0):
        return False
    vs.SetPluginStyle(obj, tag['style'])
    if member_handle is not None:
        vs.DT_AssociateWithObj(obj, member_handle)
    vs.AddVPAnnotationObject(viewport, obj)
    vs.DT_UpdateTaggedTags(obj)
    # 引出線を非表示にする。再生成でスタイルの引出線設定に戻されないよう最後に行う。
    vs.SetRField(obj, _DATA_TAG_PLUGIN, _LEADER_FIELD, _LEADER_OFF)
    vs.ResetObject(obj)
    return True


def execute_sheets(
    commands: list[SheetCommand],
    tags: list[TagCommand] | None = None,
    member_handles: dict[int, Any] | None = None,
    counters: dict[str, int] | None = None,
) -> int:
    """sheet 命令のリストを実行し、作成シート数を返す。

    ``tags`` を渡すと、各シートのビューポートに **その表示レイヤに乗る横架材**
    (タグの ``layer`` がビューポートの ``layers`` に含まれるもの)のデータタグを
    注釈として配置する。横架材レイヤは階ごとに固有なので、タグは対応する 1 枚の
    床伏図・小屋伏図にのみ載る。``member_handles`` は横架材命令のインデックス →
    構造材ハンドルの対応で、タグを対象横架材に関連付けるのに使う。``counters`` を
    渡すと配置したタグ数を ``counters['tags']`` に記録する。
    """
    tags = tags or []
    member_handles = member_handles or {}
    count = 0
    tag_count = 0
    for command in commands:
        viewport = draw_sheet(command)
        if viewport is not None and viewport != vs.Handle(0):
            vp_layers = set(command['viewport']['layers'])
            for tag in tags:
                if tag['layer'] not in vp_layers:
                    continue
                handle = member_handles.get(tag['member_index'])
                if draw_tag(tag, handle, viewport):
                    tag_count += 1
        count += 1
    if counters is not None:
        counters['tags'] = tag_count
    return count
