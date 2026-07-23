"""wall / slab 命令の描画。基礎の立上り(壁)・底盤(スラブ)を配置する。

立上りは ``vs.Wall`` で壁オブジェクトを、底盤は外形ポリゴンから
``vs.CreateSlab`` でスラブオブジェクトを生成する。いずれも高さ基準を
``SetObjectStoryBound`` でストーリレベルにバインドする(梁・柱と同じ規約)。
立上りには壁スタイル(``WALL_STYLE_NAME``)を ``SetWallStyle`` で適用する
(オフセットは 0/0 で壁芯に揃える)。

**地中梁**は台形断面の下り梁で底盤コンクリートに一体だが、**VectorScript では地中梁を
「足す」形で Slab PIO に噛み合わせられない**(VW 2026 で確認。``CreateCustomObjectPath``
は add で噛み合うが作成時ダイアログ+再実行クラッシュ、``CreateCustomObjectN`` +
``SetCustomObjectProfileGroup`` の後付けは未確定で底盤不可視、``ModifySlab`` は「選択が
間違っています」)。そのため地中梁は台形プリズムを **2 回** 作って表す(``_draw_modifier``):
(1) **削り取りモディファイア**を ``SetCustomObjectProfileGroup`` で ``CreateSlab`` の通常
スラブに渡して底盤を**削り取り(clip)**、地中梁の位置で底盤のスラブスタイルの層
(躯体・捨てコン・砕石)を除去して断面に写り込まないようにする(``_draw_modifier_group``。
以前から安定して動く挙動)。(2) 同じ台形プリズムを**独立した可視 3D ソリッド**
(``_draw_beam_solids``)として同じ ``F-底盤`` レイヤ・同じ基礎スラブクラスで置き、削り取った
位置を地中梁のコンクリートで埋める。ブール結合はしないが同一クラス・同一位置で一体に見える。
可視ソリッドには地中梁のマテリアル(``基礎コンクリート MT``)を ``SetObjMaterialHandle`` で設定する
(名前→ハンドルは ``ForEachMaterial`` 列挙で解決する。``GetObject`` はマテリアルを確実に返さない)。
モディファイアの無い底盤は削り取りをせず ``CreateSlab`` のみ。

底盤(基礎底盤系)にはスラブスタイル(``基礎スラブ - コンクリート {厚}mm /
捨てコン …mm / 砕石 …mm``)を適用する。既定=150mm はその既存スタイルをそのまま、
それ以外の厚みは既定スタイルを複製して最上層(#1)のコンクリート厚を変更した
スタイルを作って適用する(``_resolve_slab_style_ref``)。既定スタイルの探索は、
捨てコン・砕石の既定厚が将来変わりうるため、コンクリート厚(150mm)だけを固定して
残りを任意の文字列にマッチさせる(``_find_base_slab_style``)。地中梁は
スタイルを適用しない(命令の ``thickness`` が None)。

スタイルのハンドルは ``BuildResourceList`` の列挙結果から ``GetResourceFromList``
で取得する(``vs.GetObject`` はリソースマネージャのリソースを確実には返さない)。
複製は ``vs.GetParent`` で得た親コンテナへ挿入する(nil コンテナへの複製は不正な
無名リソースを作るため)。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import SlabCommand, WallCommand, WallJoinCommand

WALL_STYLE_NAME = '基礎 - 木造ベタ基礎150mm'

# --- スラブスタイル(基礎底盤)の関連付け ---
# BuildResourceList のスラブスタイル種別 ID(Vectorworks 公式の未公開一覧より)。
_SLAB_STYLE_RESOURCE_TYPE = 107
# BuildResourceList の folderIndex。0=現在のドキュメント内のリソースのみ。
_SLAB_STYLE_FOLDER = 0
# 既定スタイルのコンクリート厚 (mm)。この厚みのスラブは既存スタイルをそのまま使う。
_BASE_SLAB_CONCRETE_MM = 150
# スラブスタイル名を 3 分割する区切り(``基礎スラブ - コンクリート 150mm /
# 捨てコン 30mm / 砕石 100mm`` を先頭部・捨てコン・砕石に分ける)。
_SLAB_STYLE_SEP = ' / '
# 先頭部(コンクリート層)の接頭辞。厚みの直前まで固定し、``{接頭辞}{厚}mm`` になる。
_SLAB_STYLE_HEAD_PREFIX = '基礎スラブ - コンクリート '
# 2 番目(捨てコン)・3 番目(砕石)の部分の接頭辞。厚みの数値は将来変わりうるため
# 接頭辞だけで既定スタイルを識別し、数値部分は固定しない。
_SLAB_STYLE_BLINDING_PREFIX = '捨てコン'
_SLAB_STYLE_GRAVEL_PREFIX = '砕石'
# スラブスタイルの最上層(#1)= コンクリートのコンポーネント番号。
_CONCRETE_COMPONENT_INDEX = 1

# 壁結合(JoinWalls)の引数。capped(結合部を閉じるか)は命令ごとに指定する
# (天端高さの異なる立上りは低いほうを閉じて高いほうに結合する=capped=True、
# 同じ高さはコンクリート一体のため閉じない=capped=False)。showAlerts=False で
# 結合失敗時のダイアログを抑止する(インポート中に手動操作を求められないように)。
_JOIN_SHOW_ALERTS = False

# --- 地中梁(台形プリズム)の描画 ---
# 地中梁は底盤コンクリートに一体の下り梁だが、**VectorScript では地中梁を「足す」形で
# Slab PIO に噛み合わせることができない**(VW 2026 で確認):
#   - ``CreateCustomObjectPath('Slab', 外形, 群)`` は add で噛み合うが Slab プラグインが
#     作成時ダイアログを開く。しかも VW 自身のエクスポートを再実行すると**クラッシュ**する。
#   - ``CreateCustomObjectN``/``SetCustomObjectProfileGroup`` の後付けはスラブ編集中の
#     「新規追加」扱いで未確定になり底盤が**不可視**になる。
#   - ``ModifySlab`` は「選択が間違っています」で失敗し別図形が残る。
# そのため地中梁は台形プリズムを **2 回** 作って表す:
#   1. **削り取りモディファイア**(``_draw_modifier_group`` → ``SetCustomObjectProfileGroup``)。
#      ``CreateSlab``(通常スラブ)のプロファイル群として渡すと底盤を**削り取る(clip)**。
#      これは以前から安定して動く挙動で、底盤のスラブスタイル(躯体・捨てコン・砕石の層)を
#      地中梁の位置で除去し、地中梁断面にこれらの層が写り込まないようにする。
#   2. **可視の 3D ソリッド**(``_draw_beam_solids``)。同じ台形プリズムを独立したソリッドとして
#      底盤と同じ ``F-底盤`` レイヤ・同じ基礎スラブクラスで置き、削り取った位置を地中梁の
#      コンクリートで埋める。ブール結合はしないが、同一クラス・同一位置なので一体に見える。
# 台形断面(u=水平幅・v=鉛直)を XY 平面に描いて鉛直(+Z)に push し、断面を起こして
# 鉛直軸 v を +Z に向ける傾き(度)。続けて押し出し方向(+Z→水平)を方位角へ向ける
# 追加回転(azimuth + このオフセット、度)。幅軸 u が走る向き +90 度に一致する。
# Z は絶対値そのまま(``origin`` の z=梁下端のワールド Z)。回転規約は解析フェーズ
# (ifc/footing.py の _ground_beam_modifier)と一致させており、最終的な向き・高さ・
# 削り取りは VectorWorks 上で確認する方針(他要素と同じ)。
_MODIFIER_TILT_DEG = 90.0
_MODIFIER_AZIMUTH_OFFSET_DEG = 90.0
# 各モディファイア/地中梁ソリッドに立てるオブジェクト変数(実オブジェクトのエクスポートで
# 底盤モディファイアに False が立つ。レイヤ平面のワールド 3D として扱わせる)。
_MODIFIER_PLANE_VAR = 1160
_MODIFIER_PLANE_VALUE = False
# 地中梁の可視ソリッドに立てる「断面ビューポートで構造用図形として扱う」
# (Mark Object as Structural)。断面ビューポートで地中梁を底盤など他の構造用図形と
# 一体の構造用図形としてマージ表示させる。削り取りモディファイア(底盤の clip)には
# 不要で、可視ソリッドにのみ立てる。selector 702 は Vectorworks 公式のオブジェクト
# 変数一覧(Function Reference の Object Selectors)より。
_MARK_STRUCTURAL_VAR = 702
_MARK_STRUCTURAL_VALUE = True
# 地中梁の可視ソリッドに設定するマテリアル名。VW 側で登録したマテリアル資源名と
# 一致させる。**マテリアルはリソースマネージャのリソースで ``GetObject`` では確実に
# 取得できない**(スラブスタイルと同じ。空ハンドルが返ると ``SetObjMaterialHandle``
# が呼ばれずオブジェクトの「マテリアルを使用」も無効のまま=適用されない)。そこで
# ``ForEachMaterial`` でドキュメントの全マテリアルを列挙し ``GetName`` が一致する
# ハンドルを引き(``_find_material_handle``)、``SetObjMaterialHandle`` で割り当てる
# (有効なハンドルを渡すとオブジェクトの「マテリアルを使用」が有効になる)。ハンドルが
# 得られない(未登録=NIL)場合はマテリアルを設定しない。マテリアル名・割り当ての
# 最終挙動は他要素と同じく VectorWorks 上で確認する方針。
_GROUND_BEAM_MATERIAL = '基礎コンクリート MT'


def _find_material_handle(name: str) -> Any:
    """マテリアル名 ``name`` のハンドルを返す。無ければ空ハンドル(``Handle(0)``)。

    マテリアルはリソースマネージャのリソースで ``GetObject`` では確実に取得できない
    (スラブスタイルと同じ)。``ForEachMaterial``(ドキュメントの全マテリアルを列挙)で
    各マテリアルを走査し、``GetName`` が ``name`` に一致する最初のハンドルを返す。
    """
    matches: list[Any] = []

    def _capture(material: Any) -> None:
        if not matches and vs.GetName(material) == name:
            matches.append(material)

    vs.ForEachMaterial(False, _capture)
    return matches[0] if matches else vs.Handle(0)


def _draw_modifier(modifier: Any) -> Any:
    """地中梁 1 件を台形プリズム(押し出しソリッド)として描き、そのハンドルを返す。

    台形断面(``profile``、u=幅・v=鉛直)を XY 平面に描いて ``BeginXtrd`` で鉛直
    (0→depth)に押し出し、断面を起こして(``Rotate3D(90,0,0)``)方位角へ回し
    (``Rotate3D(0,0,azimuth+90)``)、断面原点の**絶対位置**(``origin`` の z=梁下端の
    ワールド Z)へ移動する。**Z は絶対値そのまま**にする=削り取りモディファイアとして
    底盤(パスは作図レイヤ平面=絶対 Z の基礎ストーリ)に渡しても、可視ソリッドとして
    置いても、ワールド絶対 Z で描けば正しい高さに来る。押し出しソリッドにオブジェクト変数
    1160=False(レイヤ平面のワールド 3D)を立てる(実オブジェクトのエクスポートに一致)。
    削り取り・可視ソリッドの両方でこの 1 件の描画を使う(地中梁を 2 回作る)。
    """
    profile = modifier['profile']
    ox, oy, oz = modifier['origin']
    vs.BeginXtrd(0.0, modifier['depth'])
    vs.ClosePoly()
    vs.BeginPoly()
    vs.MoveTo(profile[0][0], profile[0][1])
    for u, v in profile[1:]:
        vs.LineTo(u, v)
    vs.EndPoly()
    vs.EndXtrd()
    solid = vs.LNewObj()
    vs.SetObjectVariableBoolean(solid, _MODIFIER_PLANE_VAR, _MODIFIER_PLANE_VALUE)
    vs.ResetOrientation3D()
    vs.Rotate3D(_MODIFIER_TILT_DEG, 0.0, 0.0)
    vs.Rotate3D(0.0, 0.0, modifier['azimuth'] + _MODIFIER_AZIMUTH_OFFSET_DEG)
    vs.Move3D(ox, oy, oz)
    return solid


def _draw_modifier_group(modifiers: list[Any]) -> Any:
    """削り取りモディファイア群を 1 つのグループにまとめてハンドルを返す。

    ``SetCustomObjectProfileGroup(slab, グループ)`` で ``CreateSlab`` の通常スラブに
    渡すと底盤を**削り取る(clip)**。地中梁の位置で底盤のスラブスタイルの層
    (躯体・捨てコン・砕石)を除去し、地中梁断面にこれらが写り込まないようにする。
    """
    vs.BeginGroup()
    for modifier in modifiers:
        _draw_modifier(modifier)
    vs.EndGroup()
    return vs.LNewObj()


def _draw_beam_solids(modifiers: list[Any], class_name: str) -> None:
    """地中梁を可視の 3D ソリッドとして描く(削り取りモディファイアとは別の 2 つ目の実体)。

    削り取りで底盤から除去した位置を、同じ台形プリズムのソリッドで埋める。底盤と同じ
    基礎スラブクラス(``class_name``)を付け、同一コンクリートとして一体に見せる。
    可視ソリッドには「断面ビューポートで構造用図形として扱う」(Mark Object as
    Structural=selector 702)を立て、断面ビューポートで底盤など他の構造用図形と一体に
    マージ表示させる(削り取りモディファイアには不要で可視ソリッドにのみ立てる)。
    さらに地中梁のマテリアル(``基礎コンクリート MT``)を ``SetObjMaterialHandle`` で設定する
    (名前→ハンドルは ``ForEachMaterial`` 列挙で解決=``_find_material_handle``。有効な
    ハンドルを渡すとオブジェクトの「マテリアルを使用」が有効になる。未登録=NIL のときは
    設定しない)。
    """
    material_handle = _find_material_handle(_GROUND_BEAM_MATERIAL)
    for modifier in modifiers:
        solid = _draw_modifier(modifier)
        vs.SetClass(solid, class_name)
        vs.SetObjectVariableBoolean(
            solid, _MARK_STRUCTURAL_VAR, _MARK_STRUCTURAL_VALUE)
        if material_handle != vs.Handle(0):
            vs.SetObjMaterialHandle(solid, material_handle)


def draw_wall(command: WallCommand) -> Any:
    """wall 命令 1 件を壁オブジェクトとして描画し、壁ハンドルを返す。

    壁厚を ``DoubLines`` で設定してから ``Wall`` で壁芯線から壁を生成し、
    下端・上端の高さ基準をストーリレベルにバインドする(boundType=2=Story)。
    壁が生成できない場合は壁芯の直線にフォールバックし、None を返す(壁結合の
    対象にならないため)。

    バインドには**壁専用の ``SetWallOverallHeights``** を使う。汎用の
    ``SetObjectStoryBound`` では壁の高さ基準が確定せず、壁がデザインレイヤの
    「壁の高さ(レイヤ設定)」(Default Wall Height)に従ってしまう(構造材・
    スラブでは ``SetObjectStoryBound`` が効くが、壁は専用関数が必要)。
    ``SetWallOverallHeights`` で下端/上端を直接ストーリレベルにバインドすることで
    レイヤの壁高さ設定に依存せず実形状どおりの高さになる。story 引数(0=自階・
    1=上階・2=下階)は ``story_offset`` の 0/1 とそのまま一致する。
    """
    x1, y1 = command['start']
    x2, y2 = command['end']

    vs.DoubLines(command['thickness'])
    vs.Wall(x1, y1, x2, y2)
    obj = vs.LNewObj()
    if obj != vs.Handle(0):
        vs.SetClass(obj, command['class'])
        vs.SetWallStyle(obj, WALL_STYLE_NAME, 0.0, 0.0)
        bottom = command['bottom_bound']
        top = command['top_bound']
        vs.SetWallOverallHeights(
            obj,
            2, bottom['story_offset'], bottom['level'], bottom['offset'],
            2, top['story_offset'], top['level'], top['offset'])
        vs.ResetObject(obj)
        return obj
    # フォールバック: 壁芯の直線
    vs.MoveTo(x1, y1)
    vs.LineTo(x2, y2)
    fallback_line = vs.LNewObj()
    vs.SetClass(fallback_line, command['class'])
    return None


def _slab_style_head(concrete_mm: int) -> str:
    """コンクリート厚 ``concrete_mm`` に対応する先頭部(コンクリート層)名を返す。"""
    return f'{_SLAB_STYLE_HEAD_PREFIX}{concrete_mm}mm'


def _is_foundation_slab_style(name: str | None) -> bool:
    """スラブスタイル名が基礎底盤スタイル(コンクリート/捨てコン/砕石)の形式か。

    名前を ``' / '`` で 3 分割し、先頭が ``基礎スラブ - コンクリート …mm``、
    2 番目が ``捨てコン`` 始まり、3 番目が ``砕石`` 始まりのものを対象とする。
    捨てコン・砕石の厚みは接頭辞のみで判定し、数値部分は固定しない。
    """
    if not name:
        return False
    parts = name.split(_SLAB_STYLE_SEP)
    if len(parts) != 3:
        return False
    return (parts[0].startswith(_SLAB_STYLE_HEAD_PREFIX)
            and parts[0].endswith('mm')
            and parts[1].startswith(_SLAB_STYLE_BLINDING_PREFIX)
            and parts[2].startswith(_SLAB_STYLE_GRAVEL_PREFIX))


def _slab_style_handles() -> dict[str, Any]:
    """現在ドキュメントのスラブスタイル名→ハンドルの dict を返す。

    ``BuildResourceList``(種別 107)でスラブスタイルを列挙し、各スタイルの
    ハンドルを ``GetResourceFromList`` で引く(folderIndex=0 なので列挙されるのは
    現在ドキュメントのスタイルで、``GetResourceFromList`` はそのハンドルを返す)。

    **リソース(スラブスタイル)のハンドルは ``vs.GetObject`` では確実に取得できない**
    (``GetObject`` は名前リスト・レイヤリストを引くもので、リソースマネージャの
    リソースは対象外のことがある)。以前は ``GetObject`` で存在確認・複製元取得を
    していたため、既定 150mm スタイルが見つからず(NIL 扱いで)スタイルが一切
    適用されなかった。列挙結果のハンドルを使うことでこれを回避する。
    """
    list_id, num = vs.BuildResourceList(
        _SLAB_STYLE_RESOURCE_TYPE, _SLAB_STYLE_FOLDER, '')
    handles: dict[str, Any] = {}
    for i in range(int(num)):
        name = vs.GetNameFromResourceList(list_id, i + 1)
        handle = vs.GetResourceFromList(list_id, i + 1)
        if name and handle != vs.Handle(0):
            handles[name] = handle
    return handles


def _find_base_slab_style(styles: dict[str, Any]) -> str | None:
    """既定の基礎スラブスタイル(コンクリート 150mm)の名前を返す。無ければ None。

    ``styles``(``_slab_style_handles`` が返す名前→ハンドル)の名前のうち、先頭部が
    ``基礎スラブ - コンクリート 150mm`` で、捨てコン・砕石の部分を持つスタイルを
    既定スタイルとみなす。捨てコン・砕石の厚みは将来変わりうるため、コンクリート厚
    (150mm)だけを固定して探す(要件)。
    """
    head = _slab_style_head(_BASE_SLAB_CONCRETE_MM)
    for name in styles:
        if (_is_foundation_slab_style(name)
                and name.split(_SLAB_STYLE_SEP)[0] == head):
            return name
    return None


def _derive_style_name(base_name: str, concrete_mm: int) -> str:
    """既定スタイル名の先頭部(コンクリート厚)を ``concrete_mm`` に置換した名前。

    捨てコン・砕石の部分は既定スタイルから引き継ぐため、既定名を分割して先頭部
    だけを差し替える(例: 既定 ``… 150mm / 捨てコン 30mm / 砕石 100mm`` から
    180mm なら ``… 180mm / 捨てコン 30mm / 砕石 100mm``)。
    """
    parts = base_name.split(_SLAB_STYLE_SEP)
    parts[0] = _slab_style_head(concrete_mm)
    return _SLAB_STYLE_SEP.join(parts)


def _resolve_slab_style_ref(
    base_name: str, concrete_mm: int, styles: dict[str, Any],
) -> int | None:
    """コンクリート厚 ``concrete_mm`` のスラブスタイルの ref 番号を返す。

    目的の名前(既定名のコンクリート厚部分を ``concrete_mm`` に置換したもの)の
    スタイルが ``styles`` にあればそれを使い、無ければ既定スタイルのハンドルを複製して
    最上層(#1)のコンクリート厚を変更した新スタイルを作る。作った新スタイルは
    ``styles`` に登録するため、同一厚みの底盤が複数あっても複製は 1 回で済む。

    **リソースの複製は ``vs.GetParent`` で得た親コンテナへ挿入し、直後にユニークな
    名前を付ける**。nil コンテナへ複製すると無名の不正リソースがアクティブレイヤに
    作られてドキュメントを壊す(VW 公式ドキュメントの ``CreateDuplicateObject`` の
    注意書き)。``SetSlabStyle`` に渡す ref 番号は**スタイル名の正の内部インデックス
    ``Name2Index(name)``**(VW 上で確認: 負値=``-Name2Index`` はスタイルなしのまま
    適用されず、正値でのみ適用され ``GetSlabStyle`` も同じ正値を返す。線種等の名前付き
    リソースは負値だがスラブスタイルは正値)。作成・取得できない・名前が解決できない
    (Name2Index=0)場合は None。
    """
    target = _derive_style_name(base_name, concrete_mm)
    if target not in styles:
        base_handle = styles.get(base_name)
        # 複製元(既定スタイル)が無ければスタイルを付けない。
        if base_handle is None:
            return None
        dup = vs.CreateDuplicateObject(base_handle, vs.GetParent(base_handle))
        if dup == vs.Handle(0):
            return None
        vs.SetName(dup, target)
        vs.SetComponentWidth(dup, _CONCRETE_COMPONENT_INDEX, float(concrete_mm))
        styles[target] = dup
    ref = vs.Name2Index(target)
    return ref if ref != 0 else None


def _apply_slab_style(
    slab: Any, command: SlabCommand, base_style: str | None,
    styles: dict[str, Any] | None,
) -> None:
    """底盤スラブに厚みに応じたスラブスタイルを適用する。

    命令の ``thickness`` が None(スタイル対象外=地中梁等)、既定スタイルが
    見つからない、またはスタイル一覧が無い場合は何もしない。``styles`` は
    ``_slab_style_handles`` が返す名前→ハンドルで、新規作成したスタイルの登録先も
    兼ねる(同一厚みの複製の重複防止)。
    """
    thickness = command['thickness']
    if thickness is None or base_style is None or styles is None:
        return
    concrete_mm = int(round(thickness))
    ref = _resolve_slab_style_ref(base_style, concrete_mm, styles)
    if ref is not None:
        vs.SetSlabStyle(slab, ref)


def draw_slab(
    command: SlabCommand,
    base_style: str | None = None,
    styles: dict[str, Any] | None = None,
) -> None:
    """slab 命令 1 件をスラブオブジェクトとして描画する。

    外形ポリゴンを閉じた多角形として作成し、標準の ``CreateSlab`` でスラブにする
    (底盤の有無に関わらず確実に描画される)。**地中梁を持つ底盤は、地中梁の台形プリズムを
    2 回作って表す**(VectorScript では地中梁を「足す」形で Slab PIO に噛み合わせられない
    ため。``_draw_modifier`` 節参照):

    1. **削り取りモディファイア**: 台形プリズム群を ``SetCustomObjectProfileGroup`` で
       ``CreateSlab`` の通常スラブに渡し、底盤を**削り取る(clip)**。地中梁の位置で底盤の
       スラブスタイルの層(躯体・捨てコン・砕石)を除去し、地中梁断面に写り込まないようにする。
    2. **可視の 3D ソリッド**: 同じ台形プリズムを独立したソリッド(``_draw_beam_solids``)として
       底盤と同じ ``F-底盤`` レイヤ・同じ基礎スラブクラスで置き、削り取った位置を地中梁の
       コンクリートで埋める。

    モディファイアの無い底盤は削り取りをせず ``CreateSlab`` のみ。底盤にはコンクリート厚に
    応じたスラブスタイルを適用する(``_apply_slab_style``)。スラブ天端の絶対 Z を
    ``SetSlabHeight`` で設定し、天端の高さ基準を底盤天端レベルにバインドする。スラブが
    生成できない場合は外形ポリゴンにフォールバックする(可視の地中梁ソリッドは描く)。

    **``SetSlabHeight`` はスラブ厚ではなく天端高さ(Coordinate)を設定する**。
    以前はここに厚みを渡していたため天端が厚み分だけ高く描画されていた
    (柱・梁の高さ二重加算と同種の不具合)。スラブ厚はスラブスタイルのコンポーネント
    が決めるため、天端高さ(``elevation``、絶対 Z)を渡す。基礎ストーリは GL=0 の
    ため、この絶対 Z はストーリ基準高さと一致する。
    """
    boundary = command['boundary']
    modifiers = command.get('modifiers') or []

    vs.ClosePoly()
    vs.BeginPoly()
    vs.MoveTo(boundary[0][0], boundary[0][1])
    for point in boundary[1:]:
        vs.LineTo(point[0], point[1])
    vs.EndPoly()
    poly_h = vs.LNewObj()

    slab = vs.CreateSlab(poly_h)
    if slab != vs.Handle(0):
        vs.SetClass(slab, command['class'])
        _apply_slab_style(slab, command, base_style, styles)
        if modifiers:
            # 地中梁の台形プリズム群を削り取りモディファイアとして通常スラブに渡し、底盤の
            # スラブスタイルの層(躯体・捨てコン・砕石)を地中梁の位置で削り取る(clip)。
            group_h = _draw_modifier_group(modifiers)
            vs.SetCustomObjectProfileGroup(slab, group_h)
        vs.SetSlabHeight(slab, command['elevation'])
        bound = command['bound']
        vs.SetObjectStoryBound(
            slab, 0, 2, bound['story_offset'], bound['level'], bound['offset'])
        vs.ResetObject(slab)
    else:
        # フォールバック: 外形ポリゴン
        vs.SetClass(poly_h, command['class'])

    # 地中梁の可視の 3D ソリッド(削り取りとは別の 2 つ目の実体)を、削り取った位置に
    # 同じ基礎スラブクラスで置く。スラブが作れなくても地中梁自体は描く。
    if modifiers:
        _draw_beam_solids(modifiers, command['class'])


def execute_walls(
    commands: list[WallCommand], handles: dict[int, Any] | None = None,
) -> int:
    """wall 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。

    ``handles`` に dict を渡すと、命令のインデックス(commands 内の位置)をキーに
    配置した壁ハンドルを記録する(壁結合 ``execute_wall_joins`` の関連付けに使う。
    横架材ハンドルと同じ受け渡し方式)。フォールバック描画(壁が作れない)や
    レイヤ未生成でスキップした命令は記録しない。
    """
    count = 0
    for index, command in enumerate(commands):
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        obj = draw_wall(command)
        if handles is not None and obj is not None:
            handles[index] = obj
        count += 1
    return count


def execute_wall_joins(
    commands: list[WallJoinCommand], handles: dict[int, Any],
) -> int:
    """wall_join 命令のリストを実行して交差する立上りを結合し、結合数を返す。

    ``handles`` は ``execute_walls`` が記録した壁インデックス→壁ハンドルの dict。
    各命令の ``a`` / ``b`` で 2 つの壁ハンドルを引き、``vs.JoinWalls`` で結合する。
    どちらかの壁が未配置(レイヤ未生成・フォールバック描画でハンドル未記録)の
    命令はスキップする。ピック点は各壁の「残す側」に寄せた ``pick_a`` / ``pick_b``
    を渡す(壁芯の交点をそのまま渡すと相手壁芯上にあり残す側が曖昧で、VW が L 結合で
    コーナーを詰めず立上りが相手壁の外面まで伸びたまま残るため。解析フェーズで算出)。
    結合種別は命令の ``join_type``(1=T・2=L・3=X)を joinModifier に、
    命令の ``capped``(天端高さの異なる立上りは結合部を閉じる)を capped に渡す。
    """
    count = 0
    for command in commands:
        first = handles.get(command['a'])
        second = handles.get(command['b'])
        if first is None or second is None:
            continue
        ax, ay = command['pick_a']
        bx, by = command['pick_b']
        vs.JoinWalls(
            first, second, (ax, ay), (bx, by),
            command['join_type'], command['capped'], _JOIN_SHOW_ALERTS)
        count += 1
    return count


def execute_slabs(commands: list[SlabCommand]) -> int:
    """slab 命令のリストを描画し、配置数を返す。

    配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。

    スタイルを適用する底盤(``thickness`` を持つ命令)がある場合のみ、現在ドキュメントの
    スラブスタイル一覧(名前→ハンドル)を一度だけ取得し(``_slab_style_handles``)、
    既定スタイル名を探して(``_find_base_slab_style``)全命令で共有する。新規作成した
    スタイルは一覧に登録されるため、同一厚みのスタイル生成・列挙は繰り返さない。
    """
    needs_style = any(command.get('thickness') is not None
                      for command in commands)
    styles = _slab_style_handles() if needs_style else {}
    base_style = _find_base_slab_style(styles) if needs_style else None
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        draw_slab(command, base_style, styles)
        count += 1
    return count
