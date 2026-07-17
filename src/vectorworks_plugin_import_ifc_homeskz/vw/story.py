"""story 命令の実行。ストーリ・ストーリレベル・デザインレイヤを生成する。"""
from __future__ import annotations

from typing import Any

import vs

from ..document import StoryCommand

# 通り芯 (grid) を配置するレイヤ名。グリッド描画フェーズ (ifc/grid.py の
# TARGET_LAYER) と一致させる。vw は ifc に依存しないため定数を再掲する。
# レイヤスタックの最上段に積むため並べ替え対象に含める。
GRID_LAYER = '共通'

# 背面(スタック最下段)へ回すレイヤのレベルタイプ。床(FL)・野地板のレイヤは、
# 伏図ビューポートで柱・梁・柱記号を覆い隠さないよう、全ストーリの構造レイヤより
# 背面へまとめる。ビューポートは常にドキュメントのデザインレイヤ重ね順で描画され
# (ビューポート単位の重ね順オーバーライドは VW の API に無い)、かつ下階の柱レイヤ
# (別ストーリ)も併せて表示するため、床・野地板を各ストーリ内で下げるだけでは足りず、
# ドキュメント全体の最下段へ移す必要がある。ifc/story.py の LEVEL_FL / LEVEL_NOJIITA と
# 一致させる(vw は ifc に依存しないため定数を再掲する)。
LEVEL_FL = 'FL'
LEVEL_NOJIITA = '野地板'
_BACKGROUND_LEVEL_TYPES = (LEVEL_FL, LEVEL_NOJIITA)


def create_story_level_via_template(
    story_handle: Any, level_type: str, elevation: float, desired_layer_name: str,
) -> None:
    """Story Level Template 経由でストーリレベルとそれに紐づくレイヤを作成する。

    VW 2026 では AddStoryLevelN + AssociateLayerWithStory ではレイヤ→レベルの紐付けが
    UI 上 <なし> になるため、ドキュメントで明示的にバインドが保証されている
    CreateLevelTemplateN + AddLevelFromTemplate を使う。

    なお AddLevelFromTemplate は CreateStory の suffix を末尾に付加した名前で
    レイヤを作る (例: "1-FL-1")。意図した名前 ("1-FL") にするため、
    GetLayerForStory でハンドルを取り直して SetName でリネームする。
    """
    result = vs.CreateLevelTemplateN(desired_layer_name, 1.0, level_type, elevation, 2400.0)
    if isinstance(result, tuple):
        ok, template_idx = result
    else:
        ok, template_idx = bool(result), -1

    if not (ok and template_idx is not None and template_idx >= 0):
        return
    if not vs.AddLevelFromTemplate(story_handle, template_idx):
        return
    layer_h = vs.GetLayerForStory(story_handle, level_type)
    if layer_h != vs.Handle(0):
        vs.SetName(layer_h, desired_layer_name)


def count_layers() -> int:
    """ドキュメント内のデザインレイヤ数を返す(並べ替えループの上限に使う)。"""
    n = 0
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        n += 1
        layer_h = vs.NextLayer(layer_h)
    return n


def layer_index(target: Any) -> int:
    """レイヤ走査(FLayer→NextLayer)での target の位置を返す。無ければ -1。"""
    idx = 0
    layer_h = vs.FLayer()
    while layer_h != vs.Handle(0):
        if layer_h == target:
            return idx
        idx += 1
        layer_h = vs.NextLayer(layer_h)
    return -1


def move_layer_directly_above(target: Any, anchor: Any, max_steps: int) -> None:
    """ナビゲーション上で target レイヤを anchor レイヤの直上へ移動する。

    レイヤのスタック順はレベルの高さに縛られず、作成後に並べ替えできる。
    HMoveForward(h, False) で target を 1 段ずつ前方(=ナビゲーション上で上)へ送り、
    レイヤ走査(FLayer→NextLayer は下→上)で anchor の次が target になった時点で止める
    (= target が anchor の直上)。

    HMoveForward の第 2 引数 toFront を True にするとレイヤが**削除される**ため
    (公式ドキュメントの注意書き)、必ず False で 1 段ずつ移動する。さらに
    「False でも送り続けるとレイヤが消えることがある」という注意があるため、
    1 段送っても位置が変わらなくなったら(端に到達した)即座に打ち切る。無限ループを
    避けるため移動回数も max_steps で頭打ちにする。
    """
    if target == vs.Handle(0) or anchor == vs.Handle(0) or target == anchor:
        return
    prev_index = layer_index(target)
    for _ in range(max_steps):
        if vs.NextLayer(anchor) == target:
            return
        vs.HMoveForward(target, False)
        cur_index = layer_index(target)
        if cur_index == prev_index:
            # これ以上前方へ動かない(端に到達)。送り続けない。
            return
        prev_index = cur_index


def desired_layer_order(commands: list[StoryCommand]) -> list[str]:
    """希望するデザインレイヤのスタック順(ナビゲーション上→下)を返す。

    最上段に通り芯レイヤ (``共通``)、続いて**最上階→最下階**の順に各ストーリの
    レイヤを並べる(命令は Elevation 昇順=最下階→最上階なので逆順に辿る)。各ストーリ
    内のレイヤ順は命令の ``levels`` の並び(柱 → … → 横架材天端/軒高)に従う。

    ただし**床(FL)・野地板レイヤは全ストーリ分をまとめてスタック最下段(背面)へ
    回す**(``_BACKGROUND_LEVEL_TYPES``)。床・野地板を伏図ビューポートで柱・梁・
    柱記号より背面に描くため。ビューポートは常にドキュメントのデザインレイヤ重ね順で
    描画され、伏図には下階(別ストーリ)の柱レイヤも重ねて表示するので、床・野地板は
    各ストーリ内で下げるだけでは足りず、全構造レイヤより後ろ=ドキュメント最下段へ
    集める。最下段の中では上記と同じく最上階→最下階の順(上ほど前面)に並べる。

    例 (1階・2階・屋根):
        共通, R-柱, R-軒高, 2-柱, 2-横架材天端, 1-柱, 1-横架材天端,
        R-野地板, 2-FL, 1-FL
    """
    order: list[str] = [GRID_LAYER]
    background: list[str] = []
    for command in reversed(commands):
        for level in command['levels']:
            if level['type'] in _BACKGROUND_LEVEL_TYPES:
                background.append(level['layer'])
            else:
                order.append(level['layer'])
    return order + background


def reorder_story_layers(commands: list[StoryCommand]) -> None:
    """デザインレイヤを希望スタック順(``desired_layer_order``)どおりに並べ替える。

    AddLevelFromTemplate はレイヤをレベルの高さ順に挿入するため、柱レイヤが
    FL(最上階は軒高)レイヤの下に入り、さらにストーリ間の並びも崩れる。希望順の
    全レイヤを 1 本の並びとみなし、隣接ペアごとに上側レイヤを下側レイヤの直上へ
    移動して揃える。下のペアから順(末尾→先頭)に処理することで、上のペアを直す際に
    確定済みの下のペアを崩さない。生成されていないレイヤ(通り芯描画前の ``共通`` 等)は
    ``move_layer_directly_above`` が NIL を検出してスキップする。
    """
    max_steps = count_layers()
    if max_steps == 0:
        return
    order = desired_layer_order(commands)
    for i in range(len(order) - 2, -1, -1):
        upper = vs.GetLayerByName(order[i])
        lower = vs.GetLayerByName(order[i + 1])
        move_layer_directly_above(upper, lower, max_steps)


def execute_stories(commands: list[StoryCommand]) -> int:
    """story 命令のリストを実行し、作成階数を返す。"""
    if not commands:
        return 0

    # 命令セットに登場するレベルタイプを登場順に事前登録する
    level_types: list[str] = []
    for command in commands:
        for level in command['levels']:
            if level['type'] not in level_types:
                level_types.append(level['type'])
    for level_type in level_types:
        vs.CreateLayerLevelType(level_type)

    count = 0
    for command in commands:
        story_name = command['name']

        story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            vs.CreateStory(story_name, command['suffix'])
            story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            continue

        # ストーリ高さは CreateStory 直後・レベル追加前に設定する。
        # 直後に設定しないと「既定高さ 0 のストーリが複数」となり次の
        # CreateStory が衝突して失敗するケースがある。
        vs.SetStoryElevationN(story_h, command['elevation'])

        for level in command['levels']:
            create_story_level_via_template(
                story_h, level['type'], level['offset'], level['layer'])

        count += 1

    # スタック順の並べ替え(reorder_story_layers)は通り芯レイヤ(共通)生成後に
    # 行う必要があるため、ここでは行わず execute_document が全描画後に呼ぶ。
    return count
