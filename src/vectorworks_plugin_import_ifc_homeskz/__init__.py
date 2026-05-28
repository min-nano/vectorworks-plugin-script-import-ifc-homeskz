import ifcopenshell

import vs

from .grid import TARGET_LAYER, import_grids
from .story import import_stories

__all__ = ['run', 'import_grids', 'import_stories']


def run():
    ok, filepath = vs.GetFileN('IFCファイルを選択してください', '', 'ifc')
    if not ok:
        vs.AlrtDialog('キャンセルされました。')
        return

    try:
        vs.Message('IFCデータを解析中...')

        ifc_file = ifcopenshell.open(filepath)

        story_count, story_diag_lines = import_stories(ifc_file)
        grid_count = import_grids(ifc_file)

        vs.ClrMessage()

        msg = (
            f'読込完了: {story_count} 階のストーリ・ストーリレベル・デザインレイヤを設定し、'
            f'「{TARGET_LAYER}」レイヤに {grid_count} 本の通り芯を配置しました。\n\n'
            f'--- 診断ログ ---\n' + '\n'.join(story_diag_lines)
        )
        vs.AlrtDialog(msg)

    except Exception as e:
        vs.ClrMessage()
        vs.AlrtDialog(f'エラーが発生しました: {str(e)}')
