"""下階柱記号・小屋束記号(柱束伏図記号 PIO)の命令の組み立て。vs 非依存。

姉妹プロジェクト vectorworks-plugin-column-under-mark のカスタム PIO
「柱束伏図記号」(指定レイヤ・クラスの構造用途 4/5 の構造材を検索し、柱は ×・
小屋束は ○ の記号を各位置に描くポイントオブジェクト)を配置する命令
(column_mark 命令)を 2 種類組み立てる。

1. **下階柱記号**: 各階の伏図に「下階柱」(直下階 N-1 の柱)を記号化するため、
   横架材天端(最上階は軒高)レイヤの直上の ``n-下階柱`` レイヤに PIO を置く。
   PIO はリセットで対象レイヤ(=直下階の ``n-柱`` レイヤ)の柱を検索し各柱位置に
   記号を描く。N 階の横架材天端の下に立つ柱は直下階(N-1)の柱であるため、
   ``n-下階柱`` レイヤの PIO は ``{N-1}-柱`` レイヤを検索対象にする。最下階
   (1 階)は下に柱が無い(下は基礎)ため作らない。
2. **小屋束記号**: 母屋伏図に最上階(屋根)の小屋束を記号化するため、母屋レイヤの
   直上の ``R-小屋束`` レイヤに PIO を置く。PIO は屋根の柱レイヤ ``R-柱`` を
   検索対象とし、**検索対象クラスを小屋束クラスに絞る**ことで小屋束(○)だけを
   記号化する(柱の下階柱記号とはクラスで分けた別オブジェクトになる)。

いずれも解析フェーズで判断し、IFC のジオメトリは参照せずストーリ構成
(``collect_stories``)から決まる。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnMarkCommand
from .story import (
    LEVEL_COLUMN,
    LEVEL_KOYAZUKA_MARK,
    LEVEL_UNDER_COLUMN,
    collect_stories,
    layer_prefix_for,
)
from .structural_class import CLASS_KOYAZUKA

if TYPE_CHECKING:
    import ifcopenshell

# 記号の既定サイズ (mm)。柱束伏図記号 PIO の MarkSize に渡す。姉妹プロジェクトの
# 既定値 (core/mark.py の DEFAULT_MARK_SIZE=300mm) に合わせる。
DEFAULT_MARK_SIZE = 300.0
# 下階柱記号の検索対象クラス(空=全クラス)。直下階の柱レイヤの柱をすべて記号化する
# (直下階の柱レイヤには小屋束は含まれないため全クラスでよい)。
TARGET_CLASS = ''
# PIO の挿入点。記号は検索した柱のワールド位置に描かれ挿入点には依存しないため
# 原点でよい(座標はセンタリング済み)。
INSERTION_POINT: list[float] = [0.0, 0.0]


def build_column_mark_commands(
    ifc_file: ifcopenshell.file,
) -> list[ColumnMarkCommand]:
    """下階柱記号・小屋束記号(column_mark 命令)を組み立てて返す。

    FL ストーリごとに、直下階(N-1)の柱を記号化する下階柱記号 PIO を ``n-下階柱``
    レイヤに 1 つ置く(最下階は下に柱が無いため作らない)。加えて最上階(屋根)が
    あれば、屋根の小屋束を母屋伏図に記号化する小屋束記号 PIO を ``R-小屋束``
    レイヤに 1 つ置く(検索対象クラスを小屋束クラスに絞る)。ストーリが無ければ
    空リストを返す。
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
    # 小屋束記号: 最上階(屋根)の小屋束を母屋伏図に記号化する。屋根の柱レイヤ
    # (R-柱)を検索対象にし、クラスを小屋束クラスに絞って小屋束(○)だけを記号化
    # する(柱の下階柱記号とは別オブジェクト)。
    if n >= 1:
        top_prefix = layer_prefix_for(n - 1, True)
        commands.append({
            'layer': f'{top_prefix}-{LEVEL_KOYAZUKA_MARK}',
            'target_layer': f'{top_prefix}-{LEVEL_COLUMN}',
            'target_class': CLASS_KOYAZUKA,
            'size': DEFAULT_MARK_SIZE,
            'position': list(INSERTION_POINT),
        })
    return commands
