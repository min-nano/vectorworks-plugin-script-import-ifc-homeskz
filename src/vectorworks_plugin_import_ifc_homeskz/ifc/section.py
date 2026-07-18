"""断面ビューポート(セクションビューポート)の命令の組み立て。vs 非依存。

伏図(``ifc/sheet.py``)がモデルを真上から見た平面図をシートに配置するのに対し、
この断面は建物を **鉛直面で切断** した断面図をシートに配置する。IFC からは切断構成を
読み取らず、取り込んだ通り芯(平面の広がり)とストーリ(鉛直の広がり)から
**建物の中心を切る 1 枚の断面**を導出する。

- 平面の広がり: 通り芯(``ifc/grid.py`` の ``resolve_lines``)のバウンディングボックス。
  通り芯・横架材などは全てこの bbox 中心でセンタリングされるため、センタリング後の
  座標系では建物中心が原点付近になる。**切断線は中心 X(=0)を Y 方向に走る鉛直面**
  にし(建物を左右に分ける中央断面)、視線は -X 側から見る(添付の実オブジェクトの
  スクリプト書き出しに合わせた向き)。
- 鉛直の広がり: ストーリ(``StoryCommand`` の ``elevation``)の最小〜最大。断面の
  鉛直クリップは基礎下(最小 elevation − 余裕)〜屋根上(最大 elevation + 余裕)に広げる。

命令(``SectionCommand``)は VectorWorks の
``CreateSectionViewport(pt1, pt2, pt3, depth, startHeight, endHeight, vpLayer)`` へ
そのまま渡せる形(切断線 2 点・視線方向の第 3 点・見込み深さ・鉛直クリップ範囲)で
持つ。シートレイヤ番号は伏図の後に続けて振る。

まずは建物中心の 1 断面のみを作る。**切断位置・向き・見込み深さ・鉛直クリップ・
配置点は VectorWorks 上で最終確認する方針**(描画フェーズ ``vw/section.py`` と同じく、
本モジュール冒頭の名前付き定数に集約する)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import SectionCommand, SheetCommand, StoryCommand
from .grid import resolve_lines

if TYPE_CHECKING:
    import ifcopenshell

# 断面図シートのタイトル・図面タイトル(まずは中心 1 断面のみ)。
SECTION_TITLE = '断面図'

# 断面図の縮尺 1:N の N(伏図と同じ 1:100)。
SECTION_SCALE = 100.0

# 切断線を通り芯 bbox の Y 端からさらに外へ延ばす余裕 (mm)。建物端の材まで確実に
# 切断線の内側に入れるため、Y の広がりに前後この距離を足す。
SECTION_LINE_MARGIN = 1000.0

# 視線方向を示す第 3 点のオフセット (mm)。切断線(中心 X を Y 方向に走る)に直交する
# -X 方向へこの距離だけ離した点を「見る側」にする(添付の実オブジェクトのスクリプト
# 書き出しに合わせ -X 側から見る。向きは VW 上で確認する)。
SECTION_LOOK_OFFSET = 1000.0

# 断面の見込み深さ (mm)。切断面(中心 X)から視線方向へこの距離まで見る。建物全体の
# X 幅 + この余裕を見込み深さにし、切断面の背後の材を取りこぼさない。
SECTION_DEPTH_MARGIN = 2000.0

# 鉛直クリップの余裕 (mm)。基礎下(最小 elevation − BELOW)〜屋根上(最大
# elevation + ABOVE)まで広げ、基礎・屋根の頂部まで断面に含める。
SECTION_HEIGHT_BELOW = 1000.0
SECTION_HEIGHT_ABOVE = 5000.0

# シートレイヤ上のビューポート配置点 (mm)。VW 上で最終調整する。
SECTION_POSITION = [0.0, 0.0]

# シートレイヤ番号のフォールバック開始値。伏図が 1 枚も無い(=番号を引けない)場合に
# 使う。伏図の番号は 1(基礎伏図の予約)から連番なので、伏図があれば最大 + 1 を使う。
_SECTION_FALLBACK_NUMBER = 2


def _grid_plan_bounds(
    ifc_file: ifcopenshell.file,
) -> tuple[float, float, float, float] | None:
    """通り芯からセンタリング後の平面バウンディングボックスを返す。

    ``(min_x, max_x, min_y, max_y)`` をセンタリング後(bbox 中心 = 原点)の座標で返す。
    通り芯が 1 本も無ければ None(平面の広がりを決められないため断面を作らない)。
    """
    lines, center_x, center_y = resolve_lines(ifc_file)
    if not lines:
        return None
    xs = [x for x1, _y1, x2, _y2, _n in lines for x in (x1, x2)]
    ys = [y for _x1, y1, _x2, y2, _n in lines for y in (y1, y2)]
    return (
        min(xs) - center_x,
        max(xs) - center_x,
        min(ys) - center_y,
        max(ys) - center_y,
    )


def _next_sheet_number(sheets: list[SheetCommand]) -> str:
    """伏図の後に続く断面図のシートレイヤ番号を返す。

    伏図(``sheets``)の数値番号の最大 + 1。伏図が無ければフォールバック値を使う。
    """
    numbers = [int(s['number']) for s in sheets if s['number'].isdigit()]
    if not numbers:
        return str(_SECTION_FALLBACK_NUMBER)
    return str(max(numbers) + 1)


def build_section_commands(
    ifc_file: ifcopenshell.file,
    stories: list[StoryCommand],
    sheets: list[SheetCommand] | None = None,
) -> list[SectionCommand]:
    """断面ビューポートの section 命令を組み立てて返す。

    まずは **建物中心を Y 方向に走る鉛直面で切断した 1 枚の断面**を作る。平面の広がりは
    通り芯 bbox、鉛直の広がりはストーリ elevation の最小〜最大から導出する。通り芯が
    無い・ストーリが無い場合は空リストを返す(切断範囲を決められないため)。

    ``sheets`` を渡すとシートレイヤ番号を伏図の後に続けて振る(未指定なら
    フォールバック番号)。
    """
    bounds = _grid_plan_bounds(ifc_file)
    if bounds is None or not stories:
        return []
    min_x, max_x, min_y, max_y = bounds
    # 切断位置 = 建物中心 X(センタリング後は原点)。切断線は中心 X を Y 方向に走る。
    cut_x = 0.0
    y0 = min_y - SECTION_LINE_MARGIN
    y1 = max_y + SECTION_LINE_MARGIN
    # 見込み深さ = 建物の X 幅 + 余裕(切断面の背後の材を取りこぼさない)。
    depth = (max_x - min_x) + SECTION_DEPTH_MARGIN
    elevations = [story['elevation'] for story in stories]
    start_height = min(elevations) - SECTION_HEIGHT_BELOW
    end_height = max(elevations) + SECTION_HEIGHT_ABOVE
    number = _next_sheet_number(sheets or [])
    return [{
        'number': number,
        'title': SECTION_TITLE,
        'drawing_title': SECTION_TITLE,
        'drawing_number': number,
        'scale': SECTION_SCALE,
        'line_start': [cut_x, y0],
        'line_end': [cut_x, y1],
        # 視線方向の第 3 点: 切断線に直交する -X 方向へ離した点(見る側)。
        'look': [cut_x - SECTION_LOOK_OFFSET, (y0 + y1) / 2.0],
        'depth': depth,
        'start_height': start_height,
        'end_height': end_height,
        'position': list(SECTION_POSITION),
    }]
