"""rebar 命令の描画。基礎の配筋 PIO「鉄筋」を 3D パス図形として配置する。

各命令について、配置先レイヤ(``F-立上り`` / ``F-底盤``)をアクティブにしてから、
命令の 3D パス(梁モード=梁天端の中心線・スラブモード=底盤天端の外形)を
``vs.Poly3D`` で作り、カスタム PIO「鉄筋」を配置する。**作成時にプラグインの設定
ダイアログが開いてインポートが中断するのを防ぐため、点オブジェクトと同じ
``vs.CreateCustomObjectN``(``showPref=False`` でダイアログ抑止)で PIO を原点に作り、
``vs.SetCustomObjectPath`` で 3D パスを後付けする**(``vs.CreateCustomObjectPath`` には
ダイアログ抑止の引数が無いため使わない。詳細は ``draw_rebar`` の docstring 参照)。
その後、PIO 本体のクラスを ``vs.SetClass`` で命令の ``class`` に設定し、描画属性をすべて
クラス属性に従わせてから、モード・配筋仕様を PIO のパラメータ(レコードフィールド)に
``vs.SetRField`` で設定して ``vs.ResetObject`` でリセットする。

**リセット時に PIO 本体(=姉妹プロジェクト vectorworks-plugin-rebar のコード)が
パス・パラメータから平面線・3D 鉄筋・断面 2D コンポーネントを描く**(本リポジトリは
PIO の配置とパラメータ設定までを担い、配筋の描画ロジックは持たない)。

PIO 名「鉄筋」・パラメータ名(``Mode`` / ``MainBar`` / ``DistBar`` / ``SlabThickness`` /
``SectionSize`` / ``TopBars`` / ``BottomBars`` / ``Stirrup``)は VectorWorks 側の
プラグイン登録名(および vectorworks-plugin-rebar の ``vw/pio.py`` の ``PARAM_*``)と
一致させる必要がある。配置先レイヤが存在しない命令、PIO が作れない(プラグイン未登録で
``CreateCustomObjectN`` も ``CreateCustomObjectPath`` も NIL)命令はスキップする。
"""
from __future__ import annotations

from typing import Any

import vs

from ..document import RebarCommand

# 配筋プラグインオブジェクトの内部プラグイン名・レコード名(VectorWorks 側で
# この名前の 3D パス図形プラグインを登録すること)。
_PLUGIN_NAME = '鉄筋'
# PIO のパラメータ(レコードフィールド)名。vectorworks-plugin-rebar の
# vw/pio.py の PARAM_* と一致させる。
_PARAM_MODE = 'Mode'
_PARAM_MAIN_BAR = 'MainBar'
_PARAM_DIST_BAR = 'DistBar'
_PARAM_SLAB_THICKNESS = 'SlabThickness'
_PARAM_SECTION_SIZE = 'SectionSize'
_PARAM_TOP_BARS = 'TopBars'
_PARAM_BOTTOM_BARS = 'BottomBars'
_PARAM_STIRRUP = 'Stirrup'
# Mode ポップアップの表示値(PIO 側は表示値に "梁" を含めば梁モード、それ以外は
# スラブモードと判定する)。
_MODE_LABEL_SLAB = 'スラブ'
_MODE_LABEL_BEAM = '梁'
# CreateCustomObjectN の showPref 引数(オブジェクトの設定ダイアログの表示)。
# インポート中にダイアログで手動入力を求められないよう常に非表示にする。
_SHOW_PREF_DIALOG = False
# CreateCustomObjectN の挿入点。原点に作り、パスは SetCustomObjectPath で
# 無変換のワールド座標のまま与えるため、オブジェクトの配置は恒等(原点)にする。
_INSERT_POINT = (0.0, 0.0)


def _set_all_attributes_by_class(obj: Any) -> None:
    """オブジェクトの描画属性(太さ・色・パターン・透明度等)をすべてクラス属性に従わせる。

    ``SetClass`` はクラスを割り当てるだけで各描画属性は by-instance の既定値のまま残る
    ため、属性ごとの by-class 設定関数を個別に呼ぶ(``vw/column_mark.py`` と同じ規約)。
    リセットで再描画される鉄筋は PIO の属性を継承するため、``ResetObject`` より前に
    設定する。
    """
    vs.SetPenColorByClass(obj)
    vs.SetFillColorByClass(obj)
    vs.SetLWByClass(obj)
    vs.SetLSByClass(obj)
    vs.SetFPatByClass(obj)
    vs.SetMarkerByClass(obj)
    vs.SetOpacityByClass(obj)


def _layer_z() -> float:
    """アクティブな作図レイヤの Z(レイヤ標高)を返す。取得できなければ 0。

    ストーリレベルにバインドされたレイヤ(底盤天端の ``F-底盤`` 等)は Z(標高)を
    持ち、**3D パス図形の座標はレイヤ基準(レイヤ相対)で解釈される**ため、絶対 Z の
    パスをそのまま与えるとレイヤ標高ぶん持ち上がって描画される(``vw/roof.py`` で
    VW 上検証済みの挙動: 絶対 Z で与えるとレイヤ高さぶん余計に持ち上がる)。パス Z から
    この値を引いてレイヤ相対にすることで、パス平面(=配筋 PIO の天端基準)を目的の
    絶対 Z(底盤天端)に一致させる。コンクリート底盤は Slab ツール(``SetSlabHeight``)が
    絶対 Z に置くため、補正しないと配筋だけがレイヤ標高ぶん上に浮く。

    ``GetZVals`` が無い(VW 2018 以前)/タプルを返さない環境では 0 を返す(レイヤ
    Z=0 相当=補正なし。``vw/roof.py`` の退避と同じ堅牢化)。
    """
    try:
        z_vals = vs.GetZVals()
    except AttributeError:
        return 0.0
    if isinstance(z_vals, tuple) and z_vals and isinstance(z_vals[0], (int, float)):
        return float(z_vals[0])
    return 0.0


def _create_path(command: RebarCommand) -> Any:
    """rebar 命令の 3D パス頂点から 3D ポリゴンを作り、そのハンドルを返す。

    スラブモード(``closed=True``)は閉じた多角形、梁モード(``closed=False``)は
    開いた線として作る。作成モード(開/閉)を明示設定してから ``vs.Poly3D`` で
    全頂点を一度に与える(``vw`` の配筋 PIO 側 ``draw.py`` と同じ 3D ポリゴンの作り方)。

    命令のパス Z は絶対(ワールド)座標だが、3D パス図形はアクティブな作図レイヤ基準
    (レイヤ相対)で座標を扱うため、レイヤ標高(``_layer_z``)を引いてレイヤ相対 Z で
    与える(絶対 Z のままだとレイヤ標高ぶん浮く。``_layer_z`` の docstring 参照)。
    X・Y はレイヤ標高の影響を受けないためそのまま与える。
    """
    if command['closed']:
        vs.ClosePoly()
    else:
        vs.OpenPoly()
    layer_z = _layer_z()
    coords: list[float] = []
    for x, y, z in command['path']:
        coords.extend((x, y, z - layer_z))
    vs.Poly3D(*coords)
    return vs.LNewObj()


def _set_rebar_params(obj: Any, command: RebarCommand) -> None:
    """rebar 命令のモード・配筋仕様を PIO のパラメータに設定する。

    梁モードは SectionSize/TopBars/BottomBars/Stirrup、スラブモードは
    MainBar/DistBar/SlabThickness を設定する。Mode ポップアップは表示値
    (``梁`` / ``スラブ``)を渡す。
    """
    if command['mode'] == 'beam':
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MODE, _MODE_LABEL_BEAM)
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_SECTION_SIZE, command['section_size'])
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_TOP_BARS, command['top_bars'])
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_BOTTOM_BARS, command['bottom_bars'])
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_STIRRUP, command['stirrup'])
    else:
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MODE, _MODE_LABEL_SLAB)
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_MAIN_BAR, command['main_bar'])
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_DIST_BAR, command['dist_bar'])
        vs.SetRField(obj, _PLUGIN_NAME, _PARAM_SLAB_THICKNESS,
                     f"{command['slab_thickness']:g}")


def draw_rebar(command: RebarCommand) -> bool:
    """rebar 命令 1 件を鉄筋 PIO として配置する。

    **作成時の設定ダイアログ抑止**: 3D パス図形を ``vs.CreateCustomObjectPath`` で作ると、
    プラグインの設定によっては作成のたびに「オブジェクトの設定」ダイアログが開き、
    インポート中に配筋 1 本ごとに手動操作を求められてしまう(``CreateCustomObjectPath``
    には点オブジェクトの ``showPref`` に相当する引数が無い)。これを避けるため、点
    オブジェクトと同じ ``vs.CreateCustomObjectN``(``showPref=False`` でダイアログを抑止)で
    PIO を原点に作り、``vs.SetCustomObjectPath`` で 3D パスを後付けする(VectorWorks 公式
    ドキュメントに載るパス図形のスクリプト作成パターン)。``SetCustomObjectPath`` は
    **パスを無変換で使用する**ため、ワールド座標のパスをそのまま与えれば配置は正しくなる
    (オブジェクトは原点=恒等配置なのでパスの絶対座標がそのまま効く。一方
    ``CreateCustomObjectPath`` は先頭頂点を原点へ平行移動しオブジェクト配置に絶対位置を
    持たせるが、いずれも最終的なワールド位置は同じ)。

    ``CreateCustomObjectN`` が NIL を返す(この環境ではパス図形をこの方法で作れない)場合は
    ``vs.CreateCustomObjectPath`` にフォールバックする(作成時ダイアログが出る場合はあるが
    配筋の配置自体は行う)。どちらも作れない場合は False。

    PIO 本体のクラス・描画属性を設定してから配筋仕様のパラメータを設定し、
    ``vs.ResetObject`` でリセットする(リセット時に PIO 本体が配筋を描く)。
    """
    path_handle = _create_path(command)
    obj = vs.CreateCustomObjectN(
        _PLUGIN_NAME, _INSERT_POINT, 0.0, _SHOW_PREF_DIALOG)
    if obj != vs.Handle(0):
        # 原点に作った PIO へワールド座標のパスを無変換で設定する
        vs.SetCustomObjectPath(obj, path_handle)
    else:
        # フォールバック: パス付きで直接作成する(作成時ダイアログが出る場合がある)
        obj = vs.CreateCustomObjectPath(_PLUGIN_NAME, path_handle, vs.Handle(0))
        if obj == vs.Handle(0):
            return False
    vs.SetClass(obj, command['class'])
    _set_all_attributes_by_class(obj)
    _set_rebar_params(obj, command)
    vs.ResetObject(obj)
    return True


def execute_rebars(commands: list[RebarCommand]) -> int:
    """rebar 命令のリストを描画し、配置数を返す。

    配置先レイヤ(``F-立上り`` / ``F-底盤``)が存在しない命令はスキップする(レイヤは
    story 命令が生成する)。PIO が作れない命令も配置数に数えない。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)
        if draw_rebar(command):
            count += 1
    return count
