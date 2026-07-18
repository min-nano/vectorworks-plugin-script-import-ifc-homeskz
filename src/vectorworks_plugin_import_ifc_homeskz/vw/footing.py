"""wall / slab 命令の描画。基礎の立上り(壁)・底盤(スラブ)を配置する。

立上りは ``vs.Wall`` で壁オブジェクトを、底盤は外形ポリゴンから
``vs.CreateSlab`` でスラブオブジェクトを生成する。いずれも高さ基準を
``SetObjectStoryBound`` でストーリレベルにバインドする(梁・柱と同じ規約)。
立上りには壁スタイル(``WALL_STYLE_NAME``)を ``SetWallStyle`` で適用する
(オフセットは 0/0 で壁芯に揃える)。

**地中梁**は台形断面のため単一スラブでは描けず、底盤コンクリートに噛み合う
モディファイア(台形プリズム=3D ソリッド)にする。モディファイアを持つ底盤は、
**外形ポリゴン(パス)とモディファイア群(プロファイル群)を一緒に
``CreateCustomObjectPath('Slab', 外形, 群)`` に渡して作る**(``_draw_modifier`` /
``_draw_modifier_group``)。**噛み合わせ(足す=add)はモディファイア群を作成時に
一緒に渡した場合にだけ起きる**ことを、VW 上で「箱をスラブに噛み合わせた」実オブジェクトの
VectorScript エクスポートで確認した。``CreateSlab`` で先に底盤を作ってから
``SetCustomObjectProfileGroup`` で後付けする・``ModifySlab`` で足す方法は削り取り
(clip)になったり「選択が間違っています」で失敗して噛み合わない。作成直後に
``SetObjectVariableBoolean(slab, 1167, True)`` を立てる(エクスポートに一致)。
モディファイアの無い底盤は従来どおり ``CreateSlab`` で作る。

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

# --- 地中梁モディファイア(底盤に噛み合う台形プリズム)の描画 ---
# モディファイアを持つ底盤は、**``CreateCustomObjectPath('Slab', 外形ポリゴン,
# モディファイア群)`` で外形(パス)とモディファイア群(プロファイル群)を一緒に渡して
# 作る**。**噛み合わせ(add)はモディファイア群を作成時に一緒に渡した場合にだけ起きる**
# ことが、VW 上で「箱をスラブに噛み合わせた」実オブジェクトの VectorScript エクスポート
# で確認された(エクスポートは外形ポリゴン→モディファイア群→``CreateCustomObjectPath
# ('Slab', 外形, 群)`` の順で、その直後に ``SetObjectVariableBoolean(slab, 1167, True)``
# を呼ぶ)。``CreateSlab`` で先に底盤を作ってから ``SetCustomObjectProfileGroup`` で
# 後付けする・``ModifySlab`` で足す方法は**削り取り(clip)になったり「選択が間違って
# います」で失敗**して噛み合わない(後付けのプロファイル群は clip として働く)。手動でも
# 貫入なしで噛み合うため、断面天端を底盤へ貫入させる必要はない(モディファイアは実形状
# =絶対 Z のまま描く)。
# 台形断面(u=水平幅・v=鉛直)を XY 平面に描いて鉛直(+Z)に push し、断面を起こして
# 鉛直軸 v を +Z に向ける傾き(度)。続けて押し出し方向(+Z→水平)を方位角へ向ける
# 追加回転(azimuth + このオフセット、度)。幅軸 u が走る向き +90 度に一致する。
# 回転規約は解析フェーズ(ifc/footing.py の _ground_beam_modifier)と一致させており、
# 最終的な向き・高さは VectorWorks 上で確認する方針(他要素と同じ)。
_MODIFIER_TILT_DEG = 90.0
_MODIFIER_AZIMUTH_OFFSET_DEG = 90.0
# 底盤(Slab)PIO の内部プラグイン名。CreateCustomObjectPath に渡す。
_SLAB_PIO = 'Slab'
# CreateCustomObjectPath で作った Slab PIO の直後に立てるオブジェクト変数(実オブジェクト
# のエクスポートに一致。パス図形の底盤で True にする)。VW 上のエクスポートで確認済み。
_SLAB_PATH_OBJECT_VAR = 1167


def _draw_modifier(modifier: Any) -> None:
    """地中梁モディファイア 1 件を台形プリズム(押し出しソリッド)として描く。

    台形断面(``profile``、u=幅・v=鉛直)を XY 平面に描いて ``BeginXtrd`` で鉛直
    (0→depth)に押し出し、断面を起こして(``Rotate3D(90,0,0)``)方位角へ回し
    (``Rotate3D(0,0,azimuth+90)``)、断面原点の**絶対位置**(``origin`` の z=梁下端の
    ワールド Z)へ移動する。**Z は絶対値そのまま**にする=モディファイア群は
    ``CreateCustomObjectPath`` で底盤(パスは作図レイヤ平面=絶対 Z の基礎ストーリ)に
    渡され、モディファイア側もワールド絶対 Z で描けばそのまま正しい高さで噛み合う。
    実オブジェクトのエクスポートでもモディファイアは絶対 Z(``Move3D(x, y, 梁下端 Z)``)で
    描かれている。手動でも貫入なしで噛み合うため、断面天端の引き上げ(貫入)は行わない。
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
    vs.ResetOrientation3D()
    vs.Rotate3D(_MODIFIER_TILT_DEG, 0.0, 0.0)
    vs.Rotate3D(0.0, 0.0, modifier['azimuth'] + _MODIFIER_AZIMUTH_OFFSET_DEG)
    vs.Move3D(ox, oy, oz)


def _draw_modifier_group(modifiers: list[Any]) -> Any:
    """モディファイア群を 1 つのグループにまとめてハンドルを返す。

    ``CreateCustomObjectPath('Slab', 外形ポリゴン, グループ)`` の profile 引数に渡す。
    作成時に一緒に渡すことで底盤に**足す(噛み合わせる=add)**(後付けの
    ``SetCustomObjectProfileGroup`` では clip=削り取りになる)。
    """
    vs.BeginGroup()
    for modifier in modifiers:
        _draw_modifier(modifier)
    vs.EndGroup()
    return vs.LNewObj()


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

    外形ポリゴンを閉じた多角形として作成する。**地中梁モディファイアを持つ底盤は、
    その外形ポリゴン(パス)とモディファイア群(プロファイル群)を一緒に
    ``CreateCustomObjectPath('Slab', 外形, 群)`` に渡して作る**(台形断面の地中梁を
    底盤コンクリートに**足して噛み合わせる**。実オブジェクトの「箱をスラブに噛み合わせた」
    VectorScript エクスポートに一致)。**噛み合わせ(add)はモディファイア群を作成時に
    一緒に渡した場合にだけ起きる**: ``CreateSlab`` で先に底盤を作ってから
    ``SetCustomObjectProfileGroup`` で後付けする・``ModifySlab`` で足す方法は削り取り
    (clip)になったり「選択が間違っています」で失敗して噛み合わない。作成直後に
    ``SetObjectVariableBoolean(slab, 1167, True)`` を立てる(エクスポートに一致)。
    モディファイアの無い底盤は従来どおり ``CreateSlab`` で作る。底盤にはコンクリート厚に
    応じたスラブスタイルを適用する(``_apply_slab_style``)。スラブ天端の絶対 Z を
    ``SetSlabHeight`` で設定し、天端の高さ基準を底盤天端レベルにバインドする。スラブが
    生成できない場合は外形ポリゴンにフォールバックする。

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

    if modifiers:
        # 地中梁モディファイア群を、外形ポリゴン(パス)と一緒に CreateCustomObjectPath
        # に渡して底盤を作る。作成時に一緒に渡すことでモディファイアが底盤に足される
        # (噛み合わせ=add)。CreateSlab + SetCustomObjectProfileGroup/ModifySlab の
        # 後付けは削り取り(clip)/失敗になり噛み合わないため使わない。
        group_h = _draw_modifier_group(modifiers)
        slab = vs.CreateCustomObjectPath(_SLAB_PIO, poly_h, group_h)
        if slab != vs.Handle(0):
            vs.SetObjectVariableBoolean(slab, _SLAB_PATH_OBJECT_VAR, True)
    else:
        slab = vs.CreateSlab(poly_h)

    if slab != vs.Handle(0):
        vs.SetClass(slab, command['class'])
        _apply_slab_style(slab, command, base_style, styles)
        vs.SetSlabHeight(slab, command['elevation'])
        bound = command['bound']
        vs.SetObjectStoryBound(
            slab, 0, 2, bound['story_offset'], bound['level'], bound['offset'])
        vs.ResetObject(slab)
    else:
        # フォールバック: 外形ポリゴン
        vs.SetClass(poly_h, command['class'])


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
