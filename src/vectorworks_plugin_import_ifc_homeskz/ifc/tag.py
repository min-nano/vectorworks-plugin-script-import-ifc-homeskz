"""横架材の断面寸法データタグ命令の組み立て。vs 非依存。

床伏図・小屋伏図のビューポート注釈として、各横架材の断面寸法(120×180 等)を
表示するデータタグを配置するための命令(tag 命令)を組み立てる。IFC を直接
解析するのではなく、既に組み立て済みの横架材命令(``member`` 命令)のジオメトリから
タグの配置位置・向きを算出する。

各横架材につきタグ 1 つ。タグは横架材の中央を基準に、軸に直交する「上または左」
方向へ断面幅/2 + 余白だけオフセットした位置へ、軸方向に沿った角度で配置する。
描画フェーズ(``vw/sheet.py``)がこの命令を使い、``member_index`` が指す横架材
オブジェクトにデータタグを関連付けてビューポート注釈に置く。
"""
from __future__ import annotations

import math

from ..document import MemberCommand, TagCommand

# 適用するデータタグスタイル名(VW 側で設定した「断面寸法」スタイル)
TAG_STYLE = '断面寸法'

# タグを横架材の面からどれだけ外側へ離すか (mm)。断面幅/2(材の面まで)に
# この余白を足した距離だけ軸直交方向へオフセットする。VW 上で見え方を
# 調整する際はこの値を変える。
_TAG_OFFSET_MARGIN = 100.0

# 軸方向の XY 成分がこれ以下だと向きを決められないため既定(上)を使う
_DIR_TOL = 1e-9


def _tag_angle(dx: float, dy: float) -> float:
    """軸ベクトル (dx, dy) に沿った読みやすい文字角度 (度) を返す。

    軸の角度を (-90, 90] に正規化し、文字が上下反転しないようにする。
    """
    angle = math.degrees(math.atan2(dy, dx))
    while angle > 90.0:
        angle -= 180.0
    while angle <= -90.0:
        angle += 180.0
    return angle


def _offset_side(dx: float, dy: float) -> tuple[float, float]:
    """軸 (dx, dy) に直交する単位ベクトルのうち「上または左」を向く側を返す。

    横架材の上(東西材)または左(南北材)にタグを寄せるため、軸直交
    (±90 度回転)の 2 候補から y が大きい(上)方を選び、y が同等
    (材が南北向き)のときは x が小さい(左)方を選ぶ。
    """
    length = math.hypot(dx, dy)
    if length <= _DIR_TOL:
        return 0.0, 1.0
    px, py = -dy / length, dx / length
    # (py 優先で上、タイなら -px 優先で左) が大きい候補を選ぶ
    cand_pos = (round(py, 9), -px)
    cand_neg = (round(-py, 9), px)
    if cand_neg > cand_pos:
        return -px, -py
    return px, py


def build_tag_commands(members: list[MemberCommand]) -> list[TagCommand]:
    """横架材の member 命令から断面寸法データタグ命令のリストを組み立てる。

    横架材 1 本につきタグ 1 つ。``member_index`` は関連付け先の横架材
    (``members`` の同じ順序)を指し、描画フェーズがそのオブジェクトに
    データタグを関連付ける。位置は横架材中央を軸直交方向へオフセットした点、
    角度は軸方向に沿った読みやすい角度。
    """
    commands: list[TagCommand] = []
    for i, member in enumerate(members):
        x1, y1 = member['start']
        x2, y2 = member['end']
        dx, dy = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        px, py = _offset_side(dx, dy)
        offset = member['width'] / 2.0 + _TAG_OFFSET_MARGIN
        commands.append({
            'style': TAG_STYLE,
            'layer': member['layer'],
            'member_index': i,
            'position': [cx + px * offset, cy + py * offset],
            'angle': _tag_angle(dx, dy),
        })
    return commands
