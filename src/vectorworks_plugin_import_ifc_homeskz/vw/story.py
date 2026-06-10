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

    return count
