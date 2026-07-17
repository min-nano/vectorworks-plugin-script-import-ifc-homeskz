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
   (1 階)は下に柱が無い(下は基礎)ため作らない。**柱(×)と束(○)を別オブジェクトに
   分けるため、下階柱記号は 1 階分につき 2 つの PIO を置く**: 管柱を記号化する
   PIO(``target_class`` = 管柱クラス)と、直下階に架かる下屋根(下屋)の小屋束を
   記号化する PIO(``target_class`` = 小屋束クラス)。**通し柱には記号を付けない**
   (通し柱はこの階自身の柱レイヤにも立ち上がって描かれるため下階柱記号は不要)
   ので、管柱・小屋束の 2 クラスだけを記号化する。柱束伏図記号 PIO の
   ``TargetClass`` は 1 クラス完全一致でしか絞れないため、柱と束をそれぞれ別
   クラスの別オブジェクトに分けることで描画設定を独立して調整できる。
2. **小屋束記号**: 母屋伏図に最上階(屋根)の小屋束を記号化するため、母屋レイヤの
   直上の ``R-小屋束`` レイヤに PIO を置く。PIO は屋根の柱レイヤ ``R-柱`` を
   検索対象とし、**検索対象クラスを小屋束クラスに絞る**ことで小屋束(○)だけを
   記号化する(柱の下階柱記号とはクラスで分けた別オブジェクトになる)。
3. **断面記号**: 各階の柱レイヤ ``n-柱`` に、その柱レイヤ自身の柱・小屋束を実断面
   に合わせた記号(柱×・小屋束/)で表す PIO を重ねて置く。**記号スタイルを断面
   (``MarkStyle=断面``)にし**、検索対象レイヤ・配置レイヤをともに柱レイヤ自身、
   検索対象クラスは空(全クラス)にして、その柱レイヤの構造用途 4/5 の構造材すべてを
   記号化する。作図クラスは極細実線(``01作図-01線-02実線-01極細線``)。

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
from .structural_class import CLASS_KOYAZUKA, CLASS_KUDABASHIRA

if TYPE_CHECKING:
    import ifcopenshell

# 記号の既定サイズ (mm)。柱束伏図記号 PIO の MarkSize に渡す。姉妹プロジェクトの
# 既定値 (core/mark.py の DEFAULT_MARK_SIZE=300mm) に合わせる。
DEFAULT_MARK_SIZE = 300.0
# 柱・束の伏図記号(柱束伏図記号 PIO 本体)を作図するクラス。描画フェーズが
# vs.SetClass で PIO に設定する。検索対象クラス(target_class)とは別物。
MARK_CLASS = '01作図-04記号-04構造-一般'
# 下階柱記号の検索対象クラス。柱束伏図記号 PIO は 1 クラス完全一致でしか絞れず、
# 柱(×)と束(○)を別オブジェクトに分けて描画設定を独立調整するため、下階柱記号は
# 管柱クラスと小屋束クラスの 2 つの PIO に分ける。通し柱にはこの階自身の柱レイヤに
# も柱が描かれるため下階柱記号を付けず、管柱・小屋束の 2 クラスだけを記号化する。
TARGET_CLASS_KUDABASHIRA = CLASS_KUDABASHIRA  # 管柱(×)
TARGET_CLASS_KOYAZUKA = CLASS_KOYAZUKA        # 下屋根の小屋束(○)
# 記号スタイル(柱束伏図記号 PIO の MarkStyle パラメータに渡す値)。姉妹プロジェクト
# vectorworks-plugin-column-under-mark の normalize_style が '断面'/'section' を
# 断面記号、それ以外(空文字含む)を平面記号として解釈する。下階柱記号・小屋束記号は
# 平面記号(柱×・小屋束○・指定サイズ)、各階の柱レイヤに重ねる断面記号は断面記号
# (実断面に合わせた柱×・小屋束/)。
MARK_STYLE_PLAN = '平面'
MARK_STYLE_SECTION = '断面'
# 断面記号(各階の柱レイヤに配置する柱束伏図記号 PIO)の作図クラス。極細の実線で
# 実断面の対角線を描く。下階柱記号・小屋束記号の作図クラス(MARK_CLASS)とは別。
SECTION_MARK_CLASS = '01作図-01線-02実線-01極細線'
# PIO の挿入点。記号は検索した柱のワールド位置に描かれ挿入点には依存しないため
# 原点でよい(座標はセンタリング済み)。
INSERTION_POINT: list[float] = [0.0, 0.0]


def build_column_mark_commands(
    ifc_file: ifcopenshell.file,
) -> list[ColumnMarkCommand]:
    """下階柱記号・小屋束記号(column_mark 命令)を組み立てて返す。

    FL ストーリごとに、直下階(N-1)の柱を記号化する下階柱記号 PIO を ``n-下階柱``
    レイヤに置く(最下階は下に柱が無いため作らない)。柱(×)と束(○)を別オブジェクトに
    分けるため 1 階分につき **管柱クラス**の PIO と**小屋束クラス**の PIO の 2 つを
    置く(通し柱には記号を付けない)。加えて最上階(屋根)があれば、屋根の小屋束を
    母屋伏図に記号化する小屋束記号 PIO を ``R-小屋束`` レイヤに 1 つ置く(検索対象
    クラスを小屋束クラスに絞る)。さらに各階の柱レイヤ(``n-柱``)には、その柱
    レイヤ自身の柱・小屋束を実断面に合わせて記号化する断面記号 PIO を 1 つずつ置く
    (記号スタイル=断面・作図クラス=極細実線)。ストーリが無ければ空リストを返す。
    """
    stories = collect_stories(ifc_file)
    commands: list[ColumnMarkCommand] = []
    n = len(stories)
    for i in range(1, n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        # 直下階(i-1)は最上階になり得ない(i <= n-1 なので i-1 <= n-2)
        lower_prefix = layer_prefix_for(i - 1, False)
        under_layer = f'{prefix}-{LEVEL_UNDER_COLUMN}'
        target_layer = f'{lower_prefix}-{LEVEL_COLUMN}'
        # 管柱(×)と小屋束(○)を別クラスの別オブジェクトに分ける(通し柱は付けない)
        for target_class in (
            TARGET_CLASS_KUDABASHIRA, TARGET_CLASS_KOYAZUKA,
        ):
            commands.append({
                'layer': under_layer,
                'class': MARK_CLASS,
                'target_layer': target_layer,
                'target_class': target_class,
                'size': DEFAULT_MARK_SIZE,
                'style': MARK_STYLE_PLAN,
                'position': list(INSERTION_POINT),
            })
    # 小屋束記号: 最上階(屋根)の小屋束を母屋伏図に記号化する。屋根の柱レイヤ
    # (R-柱)を検索対象にし、クラスを小屋束クラスに絞って小屋束(○)だけを記号化
    # する(柱の下階柱記号とは別オブジェクト)。
    if n >= 1:
        top_prefix = layer_prefix_for(n - 1, True)
        commands.append({
            'layer': f'{top_prefix}-{LEVEL_KOYAZUKA_MARK}',
            'class': MARK_CLASS,
            'target_layer': f'{top_prefix}-{LEVEL_COLUMN}',
            'target_class': CLASS_KOYAZUKA,
            'size': DEFAULT_MARK_SIZE,
            'style': MARK_STYLE_PLAN,
            'position': list(INSERTION_POINT),
        })
    # 断面記号: 各階の柱レイヤ(n-柱)にその柱レイヤ自身を検索対象とする柱束伏図記号
    # PIO を重ね、断面スタイルで実断面に合わせた記号(柱×・小屋束/)を描く。対象
    # クラスは絞らず(空=全クラス)、その柱レイヤの構造用途 4/5 の構造材すべてを
    # 記号化する。柱梁伏図に柱レイヤと併せて表示される。
    for i in range(n):
        is_top = i == n - 1
        prefix = layer_prefix_for(i, is_top)
        column_layer = f'{prefix}-{LEVEL_COLUMN}'
        commands.append({
            'layer': column_layer,
            'class': SECTION_MARK_CLASS,
            'target_layer': column_layer,
            'target_class': '',
            'size': DEFAULT_MARK_SIZE,
            'style': MARK_STYLE_SECTION,
            'position': list(INSERTION_POINT),
        })
    return commands
