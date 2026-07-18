"""sheet 命令の実行。シートレイヤとビューポートを生成する。

各 sheet 命令について、シートレイヤ(プレゼンテーションレイヤ)を作成し、その上に
指定したデザインレイヤ群を表示するビューポートを 1 つ配置する。ビューポートには
命令の ``layers`` に挙げたデザインレイヤだけを表示し、それ以外のデザインレイヤは
非表示にする。クラスは伏図に必要な要素が欠けないよう既定で全表示だが、命令の
``hidden_classes`` に挙げたクラスは非表示にする(表示レイヤに乗っていてもそのクラス
だけ隠す。例: 基礎伏図の配筋クラス)。
ビューポートの縮尺は表示するデザインレイヤの縮尺に合わせる。ビューは 2D/平面
(Top/Plan)投影に確定させる(``force_plan_view``。インポート直後に 3D の「上」
ビューのように描画される不具合を防ぐ)。

シートレイヤ番号は VectorWorks ではシートレイヤ(=レイヤ)の名前がそのまま担うため、
``vs.CreateLayer`` に番号を渡してレイヤ名=シートレイヤ番号にする。シートレイヤタイトル・
ビューポートの図面タイトル・図番は オブジェクト変数(``SetObjectVariableString`` の
selector)で設定する。selector 値は VectorWorks 公式のオブジェクト変数一覧に基づく
(``document.py`` のスキーマ参照)。

さらに legend 命令を渡すと、番号が一致するシートレイヤ上にグラフィック凡例(VW 標準の
「グラフィック凡例」PIO)を配置する(基礎伏図のアンカーボルト凡例、各柱梁伏図・母屋
伏図のシンボル凡例)。凡例のデータソース(=シンボルをソースにし各伏図ビューポートで
フィルタする設定)・集計基準・行レイアウトは PIO のパラメータでは設定できないため、
ユーザーが VW 側で用意したグラフィック凡例スタイル(命令の ``style``。基礎伏図=
``基礎伏図凡例``、床伏図・母屋伏図=``床伏図凡例``)を SetPluginStyle で関連付ける方式に
する(構造材・データタグと同じプラグインスタイル方式)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import LegendCommand, SheetCommand, TagCommand, ViewportCommand

# データタグの内部プラグイン名(VW の Data Tag ツール)。VW で最終確認する。
_DATA_TAG_PLUGIN = 'Data Tag'

# グラフィック凡例の内部プラグイン名(VW 標準の「グラフィック凡例」ツール)。
# 表示名は「グラフィック凡例」だが、CreateCustomObjectN に渡す内部登録名は
# 'GraphicLegend'(スペース無し)。VW 上で GetParametricRecord + GetName で
# 実オブジェクトから確認済み。
_GRAPHIC_LEGEND_PLUGIN = 'GraphicLegend'

# グラフィック凡例のプラグインスタイル方式。凡例のデータソース(=シンボルを
# ソースにし各伏図ビューポートでフィルタする設定)・集計基準・行レイアウト等は
# PIO のパラメータ(SetRField)では設定できない(ソース定義 DefineSource は
# type=14 のボタンフィールドで、選択したソースを保持する文字列フィールドが
# パラメトリックレコードに存在しないことを実オブジェクトのフィールドダンプで確認済み)。
# そこでユーザーが VW 側でソース定義まで含めたグラフィック凡例スタイルを用意し、
# 描画フェーズは配置した凡例 PIO にこのスタイルを SetPluginStyle で関連付けるだけに
# する(構造材の '木質構造材_横架材'・データタグの '断面寸法' と同じプラグインスタイル
# 方式)。**関連付けるスタイル名は legend 命令の 'style' が持つ**(基礎伏図=
# '基礎伏図凡例'、床伏図・母屋伏図='床伏図凡例')。以下は基礎伏図の既定スタイル名で、
# 参照・テスト用に残す(描画では命令の 'style' を使う)。VW 側の登録名と一致させる。
_GRAPHIC_LEGEND_STYLE = '基礎伏図凡例'

# グラフィック凡例の箱幅パラメータ。グラフィック凡例は矩形モード PIO で、対話的に
# 作成するときはユーザーが描いた矩形の幅にレイアウトが追従する(サイズは OIP に
# 出ない)。CreateCustomObjectN は点でしか生成できず、そのままだと箱幅 0 =
# サイズ 0 でリサイズハンドルを掴めない。そこで生成後に箱幅フィールド BoxWidth を
# 既定値に設定し、ResetObject で反映してから可視化する(高さは行内容から自動決定
# されるため設定しない)。フィールド名 'BoxWidth' は VW 上で実オブジェクトの
# パラメトリックレコードから確認済み。既定幅はシートレイヤ上(用紙、ドキュメント単位
# =mm)の適当な大きさで、VW 上で最終調整する。SetRField には文字列で渡す。
_LEGEND_WIDTH_FIELD = 'BoxWidth'
_LEGEND_BOX_WIDTH = '150'

# グラフィック凡例の描画属性(オブジェクト別に直接設定する)。グラフィック凡例 PIO は
# クラス(本体クラス・カレントクラスとも)では凡例の枠線・セルの見た目を制御できない
# (VW 上でクラスを設定しても一般クラスの属性で作図される)ため、クラスによる制御は
# 諦め、線の太さ・塗りをオブジェクトの属性として直接設定する。
# 線の太さ 0.13mm(SetLW の単位はミル=1/1000 インチ。0.13mm ≒ 5 ミル=0.127mm を VW は
# 0.13mm と表示する)。
_LEGEND_LINE_WEIGHT_MILS = 5
# 塗り=なし(SetFPat の塗りパターン 0 = なし)。
_LEGEND_FILL_NONE = 0

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
_VP_CLASS_HIDDEN = 1

# ビューポートのビュー(投影)を制御するオブジェクト変数 selector(公式のオブジェクト
# セレクタ一覧より)。「2D/平面」(Top/Plan)は View Type の列挙値ではなく
# 「Project 2D」ブール(1005)が担う(True=2D/平面, False=3D ビュー)。
# CreateVP はビューを Top/Plan(2D/平面)で作るためオブジェクト情報パレット上は
# 「2D/平面」と表示されるが、インポート直後はレンダーキャッシュが古いまま 3D の
# 「上」ビューのように描画され、表示と食い違う。ユーザーの手動対処(一度「上」に
# 切り替えてから「2D/平面」に戻すと正しく描画される)と同じく Project 2D を
# いったん OFF(=「上」)にして更新し、再度 ON(=「2D/平面」)に戻すことで
# 2D/平面 のキャッシュを作り直す。
_OV_VP_PROJECT_2D = 1005  # Project 2D(BOOLEAN): True=2D/平面(Top/Plan), False=3D
_OV_VP_VIEW_TYPE = 1007   # View Type(INTEGER): 3D ビューの向き
_VP_VIEW_TOP = 7          # viewTop(「上」)


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


def configure_viewport_classes(
    viewport: Any, hidden_classes: list[str] | None = None,
) -> None:
    """ビューポートでクラスの表示/非表示を設定する。

    ビューポートは既定で一部クラスが非表示になることがあるため、ドキュメントの
    全クラス(``ClassNum``/``ClassList``)を辿って表示に設定する。表示レイヤは
    ``configure_viewport_layers`` で絞り込むが、クラスは伏図に必要な要素が欠けない
    よう既定で全て表示する。ただし ``hidden_classes`` に挙げたクラスは非表示にする
    (表示レイヤに乗っていてもそのクラスの図形だけ隠す。例: 基礎伏図の配筋クラスを
    隠し、断面でのみ表示する)。
    """
    hidden = set(hidden_classes or [])
    for i in range(1, vs.ClassNum() + 1):
        name = vs.ClassList(i)
        visibility = _VP_CLASS_HIDDEN if name in hidden else _VP_CLASS_VISIBLE
        vs.SetVPClassVisibility(viewport, name, visibility)


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


def force_plan_view(viewport: Any) -> None:
    """ビューポートを 2D/平面(Top/Plan)投影で正しく描画させる。

    ``CreateVP`` はビューを Top/Plan(2D/平面)で作るためオブジェクト情報パレット上は
    「2D/平面」と表示されるが、インポート直後はレンダーキャッシュが古いまま 3D の
    「上」ビューのように描画され、表示と食い違う。ユーザーの手動対処(一度「上」に
    切り替えてから「2D/平面」に戻す)と同じく、View Type を「上」にして Project 2D を
    いったん OFF(=「上」)にし ``vs.UpdateVP`` で更新してから、再度 ON(=「2D/平面」)に
    戻すことで 2D/平面 のキャッシュを作り直す。最終的な ``vs.UpdateVP`` は
    ``draw_viewport`` が呼ぶため、この関数を抜けた時点の投影は 2D/平面 になっている。
    """
    vs.SetObjectVariableInt(viewport, _OV_VP_VIEW_TYPE, _VP_VIEW_TOP)
    vs.SetObjectVariableBoolean(viewport, _OV_VP_PROJECT_2D, False)
    vs.UpdateVP(viewport)
    vs.SetObjectVariableBoolean(viewport, _OV_VP_PROJECT_2D, True)


def draw_viewport(
    viewport: ViewportCommand, sheet_layer: Any,
) -> Any:
    """シートレイヤ上にビューポートを 1 つ生成し、生成したビューポートハンドルを返す。

    ``vs.CreateVP`` でシートレイヤ上にビューポートを作り、表示レイヤを絞り込み、
    ビューを 2D/平面(Top/Plan)投影に確定させ、図面タイトル・図番を設定してから
    ``vs.UpdateVP`` で描画を更新する。ビューポートが生成できない場合は None を返す。
    """
    obj = vs.CreateVP(sheet_layer)
    if obj == vs.Handle(0):
        return None
    vs.SetName(obj, viewport['drawing_title'])
    configure_viewport_layers(obj, viewport['layers'], sheet_layer)
    configure_viewport_classes(obj, viewport.get('hidden_classes'))
    configure_viewport_scale(obj, viewport['layers'])
    force_plan_view(obj)
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_TITLE, viewport['drawing_title'])
    vs.SetObjectVariableString(obj, _OV_VP_DRAWING_NUMBER, viewport['drawing_number'])
    vs.UpdateVP(obj)
    return obj


def draw_sheet(command: SheetCommand) -> tuple[Any, Any]:
    """sheet 命令 1 件をシートレイヤ + ビューポートとして描画する。

    シートレイヤ(プレゼンテーションレイヤ)を **シートレイヤ番号を名前として**
    作成し(VW ではシートレイヤ番号はレイヤ名が担う)、シートレイヤタイトルを
    設定してから、その上にビューポートを配置する。同じ番号のシートレイヤが既にある
    場合は再利用する。``(シートレイヤ, ビューポート)`` のタプルを返す(グラフィック
    凡例はシートレイヤ上に置くため、呼び出し側がシートレイヤハンドルも使う)。
    シートレイヤが作れない場合は ``(None, None)``、ビューポートが作れない場合は
    ``(シートレイヤ, None)`` を返す。
    """
    number = command['number']
    sheet_layer = vs.GetObject(number)
    if sheet_layer == vs.Handle(0):
        sheet_layer = vs.CreateLayer(number, _SHEET_LAYER_TYPE)
    if sheet_layer == vs.Handle(0):
        return None, None
    vs.SetObjectVariableString(sheet_layer, _OV_SHEET_TITLE, command['title'])
    return sheet_layer, draw_viewport(command['viewport'], sheet_layer)


def draw_tag(tag: TagCommand, member_handle: Any, viewport: Any) -> bool:
    """tag 命令 1 件をビューポート注釈のデータタグとして描画する。

    ``vs.CreateCustomObject`` でデータタグ(``断面寸法`` スタイル)を挿入位置・
    軸方向の角度で作り、「引出線を表示」を OFF にしてから対象の横架材
    (``member_handle``)に関連付け、ビューポートの注釈に追加する。関連付け対象が
    無い(横架材がフォールバック描画等でハンドルを持たない)場合は関連付けを省く。
    タグが作れなければ False。
    """
    x, y = tag['position']
    obj = vs.CreateCustomObject(_DATA_TAG_PLUGIN, (x, y), tag['angle'])
    if obj == vs.Handle(0):
        return False
    vs.SetPluginStyle(obj, tag['style'])
    # 引出線を非表示にする(部材に接して置いても既定 ON だと引出線が描かれるため)。
    vs.SetRField(obj, _DATA_TAG_PLUGIN, _LEADER_FIELD, _LEADER_OFF)
    vs.ResetObject(obj)
    if member_handle is not None:
        vs.DT_AssociateWithObj(obj, member_handle)
    vs.AddVPAnnotationObject(viewport, obj)
    vs.DT_UpdateTaggedTags(obj)
    return True


def draw_legend(legend: LegendCommand, sheet_layer: Any) -> bool:
    """legend 命令 1 件をシートレイヤ上のグラフィック凡例として配置する。

    配置先シートレイヤ(``legend['number']`` = レイヤ名)をアクティブにしてから、
    ``vs.CreateCustomObjectN`` でグラフィック凡例 PIO を挿入位置に作る。第 4 引数
    ``showPref=False`` でインポート中に設定ダイアログが開くのを防ぐ。**グラフィック凡例
    PIO はクラス(本体クラス・カレントクラスとも)では凡例の枠線・セルの見た目を制御
    できない**(VW 上でクラスを設定・カレントクラスを切り替えても一般クラスの属性で
    作図される)。そのためクラスによる制御は諦め、**線の太さ・塗りをオブジェクトの属性
    として直接設定する**(``vs.SetLW`` で線の太さ 0.13mm、``vs.SetFPat`` で塗りなし)。
    続いてユーザーが VW 側で用意したグラフィック凡例スタイル(``legend['style']``。
    基礎伏図=``基礎伏図凡例``、床伏図・母屋伏図=``床伏図凡例``)を ``vs.SetPluginStyle`` で
    関連付ける。凡例のデータソース(=シンボルをソースにし各伏図ビューポートで
    フィルタする設定)・集計基準・行レイアウトはこのスタイルが持つ(PIO のパラメータ
    では設定できないため。モジュール冒頭の定数コメント参照)。生成直後は矩形モード
    PIO の箱幅が 0 でサイズ 0(リサイズハンドルを掴めない)ため、スタイル関連付けの
    後に箱幅フィールド ``BoxWidth`` を既定値に設定し ``vs.ResetObject`` で反映して
    可視化する(箱幅は by-instance のジオメトリでスタイルは決めない。高さは行内容から
    自動決定される)。線の太さ・塗りの属性は最後(``ResetObject`` の後、かつ後段の
    ``UpdateStyledObjects`` によるセル再計算より前)に設定し、by-instance の属性として
    保持させる。PIO が作れない場合は False を返す。
    """
    x, y = legend['position']
    # シートレイヤ番号はレイヤ名が担うため、番号でシートレイヤをアクティブにする
    vs.Layer(legend['number'])
    obj = vs.CreateCustomObjectN(_GRAPHIC_LEGEND_PLUGIN, (x, y), 0, False)
    if obj == vs.Handle(0):
        return False
    # ソース定義(シンボル + 各伏図ビューポートフィルタ)・集計基準・行レイアウトを
    # 持つプラグインスタイルを関連付ける。ソースは PIO パラメータでは設定できないため
    # スタイルに焼き込む方式(構造材・データタグと同じ SetPluginStyle 方式)。
    vs.SetPluginStyle(obj, legend['style'])
    # 点で生成すると箱幅 0 = サイズ 0 でハンドルを掴めないため、既定の箱幅を与えて
    # 可視化する(矩形を描いて作るときの幅に相当。レイアウトが幅に追従する)。
    vs.SetRField(obj, _GRAPHIC_LEGEND_PLUGIN, _LEGEND_WIDTH_FIELD, _LEGEND_BOX_WIDTH)
    vs.ResetObject(obj)
    # クラスでは見た目を制御できないため、線の太さ(0.13mm)・塗り(なし)を
    # オブジェクトの属性として直接設定する。
    vs.SetLW(obj, _LEGEND_LINE_WEIGHT_MILS)
    vs.SetFPat(obj, _LEGEND_FILL_NONE)
    return True


def execute_sheets(
    commands: list[SheetCommand],
    tags: list[TagCommand] | None = None,
    member_handles: dict[int, Any] | None = None,
    counters: dict[str, int] | None = None,
    legends: list[LegendCommand] | None = None,
) -> int:
    """sheet 命令のリストを実行し、作成シート数を返す。

    ``tags`` を渡すと、各シートのビューポートに **その表示レイヤに乗る横架材**
    (タグの ``layer`` がビューポートの ``layers`` に含まれるもの)のデータタグを
    注釈として配置する。横架材レイヤは階ごとに固有なので、タグは対応する 1 枚の
    床伏図・小屋伏図にのみ載る。``member_handles`` は横架材命令のインデックス →
    構造材ハンドルの対応で、タグを対象横架材に関連付けるのに使う。``legends`` を
    渡すと、シートレイヤ番号(``number``)が一致するシートのシートレイヤ上に
    グラフィック凡例(基礎伏図のアンカーボルト凡例)を配置する。``counters`` を
    渡すと配置したタグ数・凡例数を ``counters['tags']`` / ``counters['legends']`` に
    記録する。

    なお、床・野地板レイヤを最背面へ回す並べ替え(``reorder_story_layers``)の結果は
    **インポート直後のビューポート描画には反映されない**(レイヤパレット・ビュー
    ポートのプロパティ上は新しい順なのに描画だけ古い順で床が柱梁を覆い隠す)。VW 上の
    検証で、並べ替えは既存ビューポートを out-of-date にせず、``UpdateVP`` も
    ``ReDrawAll`` も ``Project 2D`` トグルによる強制再描画も効かないことを確認した
    (手動「ビューポートを更新」またはファイルの開き直しでのみ反映される)。スクリプト
    内での自動反映は VW の制約上できないため、無駄な更新処理は行わず、この描画反映は
    ユーザーの手動操作に委ねる(``document.py`` のスキーマ・上位の ``execute_document``
    参照)。
    """
    tags = tags or []
    member_handles = member_handles or {}
    legends = legends or []
    count = 0
    tag_count = 0
    legend_count = 0
    # 実際に配置した凡例のスタイル名(基礎伏図凡例・床伏図凡例など)。全配置後に
    # スタイルごとに 1 回ずつ UpdateStyledObjects を呼び、ソースからセルを再計算する。
    placed_styles: set[str] = set()
    for command in commands:
        sheet_layer, viewport = draw_sheet(command)
        if viewport is not None and viewport != vs.Handle(0):
            vp_layers = set(command['viewport']['layers'])
            for tag in tags:
                if tag['layer'] not in vp_layers:
                    continue
                handle = member_handles.get(tag['member_index'])
                if draw_tag(tag, handle, viewport):
                    tag_count += 1
        # グラフィック凡例はシートレイヤ上に置く(ビューポート注釈ではない)ため、
        # シートレイヤが作れていれば番号が一致する凡例を配置する。
        if sheet_layer is not None and sheet_layer != vs.Handle(0):
            for legend in legends:
                if legend['number'] != command['number']:
                    continue
                if draw_legend(legend, sheet_layer):
                    legend_count += 1
                    placed_styles.add(legend['style'])
        count += 1
    # グラフィック凡例を配置したら、スタイルが決める内容(ソースから集めたセル=
    # シンボル)をインスタンスへプッシュするため、全配置後に**使用した各スタイル**
    # (基礎伏図凡例・床伏図凡例)ごとに 1 回ずつ UpdateStyledObjects を呼ぶ
    # (構造材・柱と同じ規約)。SetPluginStyle + ResetObject だけでは
    # スタイルのソースからセルが再計算されず、凡例が空(セル 0 個 = 幅 0)のままに
    # なる(VW 上でスタイル編集ダイアログを開いて OK すると反映されるのと同じ
    # 再計算を、この呼び出しが担う)。by-instance の個別フィールド(BoxWidth・線の太さ・
    # 塗り等)は保持したまま by-style の内容のみ更新される。
    for style in sorted(placed_styles):
        vs.UpdateStyledObjects(style)
    if counters is not None:
        counters['tags'] = tag_count
        counters['legends'] = legend_count
    return count
