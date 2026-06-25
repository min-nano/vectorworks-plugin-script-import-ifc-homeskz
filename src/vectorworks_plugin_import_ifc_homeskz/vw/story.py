"""story 命令の実行。ストーリ・ストーリレベル・デザインレイヤを生成する。"""
from __future__ import annotations

from typing import Any

import vs

from ..document import StoryCommand


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


def reorder_story_layers(commands: list[StoryCommand]) -> None:
    """各 story 命令の levels 順(上→下)どおりにデザインレイヤを並べ替える。

    AddLevelFromTemplate はレイヤをレベルの高さ順に挿入するため、柱レイヤが
    FL(最上階は軒高)レイヤの下に入ってしまう。命令の levels の並びを希望スタック順
    (上→下)とみなし、各隣接ペアについて上側レイヤを下側レイヤの直上へ移動して揃える。
    下のペアから順に処理することで、上のペアを直す際に確定済みの下のペアを崩さない。
    """
    max_steps = count_layers()
    if max_steps == 0:
        return
    for command in commands:
        levels = command['levels']
        for i in range(len(levels) - 2, -1, -1):
            upper = vs.GetLayerByName(levels[i]['layer'])
            lower = vs.GetLayerByName(levels[i + 1]['layer'])
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

    # 全レイヤ生成後にスタック順を命令どおり(柱を FL/軒高 の直上)へ揃える。
    reorder_story_layers(commands)

    return count
