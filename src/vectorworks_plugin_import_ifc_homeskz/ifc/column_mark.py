"""下階柱記号(柱束伏図記号 PIO)の命令の組み立て。vs 非依存。

各階の伏図に「下階柱」(直下階 N-1 の柱)を記号化するため、横架材天端(最上階は
軒高)レイヤの直上の ``n-下階柱`` レイヤにカスタム PIO「柱束伏図記号」(姉妹
プロジェクト vectorworks-plugin-column-under-mark)を配置する命令(column_mark
命令)を組み立てる。PIO は配置後のリセットで対象レイヤ(=直下階の ``n-柱`` レイヤ)
の柱を検索し、各柱位置に記号を描く(柱が編集されれば記号も追随する)。

対象の対応: N 階の横架材天端(最上階は軒高)の下に立つ柱は直下階(N-1)の柱で
あるため、``n-下階柱`` レイヤの PIO は ``{N-1}-柱`` レイヤを検索対象にする。
最下階(1 階)は下に柱が無い(下は基礎)ため作らない。この判断は解析フェーズで
行い、IFC のジオメトリは参照せずストーリ構成(``collect_stories``)から決まる。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnMarkCommand
from .story import (
    LEVEL_COLUMN,
    LEVEL_UNDER_COLUMN,
    collect_stories,
    layer_prefix_for,
)

if TYPE_CHECKING:
    import ifcopenshell

# 記号の既定サイズ (mm)。柱束伏図記号 PIO の MarkSize に渡す。姉妹プロジェクトの
# 既定値 (core/mark.py の DEFAULT_MARK_SIZE=300mm) に合わせる。
DEFAULT_MARK_SIZE = 300.0
# 検索対象クラス(空=全クラス)。直下階の柱レイヤの柱をすべて記号化する。
TARGET_CLASS = ''
# PIO の挿入点。記号は検索した柱のワールド位置に描かれ挿入点には依存しないため
# 原点でよい(座標はセンタリング済み)。
INSERTION_POINT: list[float] = [0.0, 0.0]


def build_column_mark_commands(
    ifc_file: ifcopenshell.file,
) -> list[ColumnMarkCommand]:
    """各階の下階柱記号(column_mark 命令)を組み立てて返す。

    FL ストーリごとに、直下階(N-1)の柱を記号化する PIO を ``n-下階柱`` レイヤに
    1 つ置く。最下階(下に柱が無い)は作らないため、ストーリ数 - 1 個の命令を返す
    (ストーリが 1 つ以下なら空リスト)。
    """
    stories = collect_stories(ifc_file)
    commands: list[ColumnMarkCommand] = []
    n = len(stories)
    for i in range(1, n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        # 直下階(i-1)は最上階になり得ない(i <= n-1 なので i-1 <= n-2)
        lower_prefix = layer_prefix_for(i - 1, False)
        commands.append({
            'layer': f'{prefix}-{LEVEL_UNDER_COLUMN}',
            'target_layer': f'{lower_prefix}-{LEVEL_COLUMN}',
            'target_class': TARGET_CLASS,
            'size': DEFAULT_MARK_SIZE,
            'position': list(INSERTION_POINT),
        })
    return commands
