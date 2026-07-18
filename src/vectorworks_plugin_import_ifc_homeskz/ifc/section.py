"""軸組図の断面ビューポート(section 命令)の組み立て。vs 非依存。

断面ビューポートは VectorScript で新規作成できないため、あらかじめシートレイヤ ``A``
(タイトル 軸組図)に ``X1``..``X20`` / ``Y1``..``Y20`` の 40 枚を用意しておき、その
**断面指示線とビューポートの位置・図番・タイトルだけを操作**する。本モジュール(解析
フェーズ)は「どの通りをどの既製ビューポートに割り当て、どんな名前にするか」を決めて
section 命令にする。実際の指示線移動・改名・削除・整列は描画フェーズ(``vw/section.py``)。

**切断位置の検出**: 柱(``ColumnCommand``)と梁(横架材 ``MemberCommand``)の両方が通る
通りだけを対象にする(柱だけ・梁だけの通りは対象外)。X通り(定 X・鉛直な断面)は、
ある X 座標に柱があり、かつ **その通りに平行=Y 方向に走る梁** がある位置。Y通り
(定 Y・水平な断面)は、ある Y 座標に柱があり、かつ **X 方向に走る梁** がある位置。
柱・梁の中心座標をクラスタリングし、両方を含むクラスタの平均(=柱梁の芯)を切断位置にする。

**命名**: 切断位置が名前付き通り芯(``IfcGridAxis``)に一致すればその名前、しなければ
**中間の通り**として直前(座標の小さい側)の名前付き通りを基準に、その通りの書式で付番
する。数字書式(``X1``/``X2``)なら ``'`` を足して ``X1'`` / ``X1''``、いろは書式
(``い``/``ろ``/``は``)なら ``又`` を前置して ``又い`` / ``又又い``(中間の順番ぶんだけ
増やす)。書式は通り芯名がいろは文字だけなら「いろは書式」、それ以外は「数字書式」。

**割り当て**: X通りの切断位置を昇順に既製ビューポート ``X1``, ``X2``, … へ、Y通りを
``Y1``, ``Y2``, … へ順に割り当てる(既製は各方向 20 枚まで)。``drawing_number`` は
上記の通りの名前、``source_number`` は流用する既製図番。

切断位置・命名・割り当ての各値(クラスタ許容・通り芯一致許容・断面線の余白など)は
本モジュール冒頭の名前付き定数に集約する。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..document import ColumnCommand, MemberCommand, SectionCommand
from .grid import CLASS_X, determine_class, resolve_lines

if TYPE_CHECKING:
    import ifcopenshell

# 各方向に用意した既製ビューポートの最大枚数(X1..X20 / Y1..Y20)。切断位置がこれを
# 超えたぶんは割り当てられない(既製が足りない)ため切り捨てる。
MAX_PER_DIRECTION = 20

# 図面タイトルの接尾辞(図番 + これ)。X1 → "X1通り"。
TITLE_SUFFIX = '通り'

# 柱・梁の中心座標を 1 本の通りにまとめるクラスタ許容 (mm)。同一の通りに乗る柱・梁は
# ほぼ同一座標(IFC で通り芯に一致)なので小さめ。隣の通り(半モジュール≈455mm 以上)を
# 巻き込まない値にする。
CLUSTER_TOL = 100.0

# 切断位置(柱梁の芯)が名前付き通り芯に一致するとみなす許容 (mm)。一致すればその通り芯
# 名を使い、外れれば中間の通りとして命名する。
AXIS_MATCH_TOL = 50.0

# 断面指示線を通り芯 bbox の端からさらに外へ延ばす余白 (mm)。指示線 2 点はこの余白を
# 足した範囲にする(既製の指示線は長さを変えず、この 2 点の中点・向きへ移動・回転する)。
SECTION_LINE_MARGIN = 1000.0

# いろは順(中間通りの「又」書式判定に使う)。通り芯名がこの文字だけで構成されていれば
# いろは書式、そうでなければ数字書式(``'`` を足す)とみなす。
_IROHA = set('いろはにほへとちりぬるをわかよたれそつねならむうゐのおくやまけふこえて'
             'あさきゆめみしゑひもせす')


def _is_iroha_name(name: str) -> bool:
    """通り芯名がいろは文字だけで構成されるか(中間通りを「又」書式にするか)。"""
    return bool(name) and all(c in _IROHA for c in name)


def _named_axes(
    ifc_file: ifcopenshell.file,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """名前付き通り芯を方向別に (name, 座標) の昇順リストで返す。

    X通り(定 X の鉛直線)は座標=X、Y通り(定 Y の水平線)は座標=Y(いずれもグリッド
    中心でセンタリング済み)。無名の通り芯は命名に使えないため除外する。同名の通り芯が
    複数区間に分かれていても 1 つにまとめる。
    """
    lines, cx, cy = resolve_lines(ifc_file)
    x_axes: dict[str, float] = {}
    y_axes: dict[str, float] = {}
    for x1, y1, x2, y2, name in lines:
        if not name:
            continue
        cx1, cy1, cx2, cy2 = x1 - cx, y1 - cy, x2 - cx, y2 - cy
        if determine_class(name, cx1, cy1, cx2, cy2) == CLASS_X:
            # 鉛直=定 X。座標は X(始終点でほぼ同じなので中点)。
            x_axes.setdefault(name, (cx1 + cx2) / 2.0)
        else:
            y_axes.setdefault(name, (cy1 + cy2) / 2.0)
    return (
        sorted(x_axes.items(), key=lambda kv: kv[1]),
        sorted(y_axes.items(), key=lambda kv: kv[1]),
    )


def _clusters(tagged: list[tuple[float, str]], tol: float) -> list[tuple[float, set[str]]]:
    """(座標, 種別) の並びを座標でクラスタリングし (平均座標, 種別集合) を返す。"""
    if not tagged:
        return []
    ordered = sorted(tagged, key=lambda t: t[0])
    result: list[tuple[float, set[str]]] = []
    group: list[float] = [ordered[0][0]]
    kinds: set[str] = {ordered[0][1]}
    for coord, kind in ordered[1:]:
        if coord - group[-1] > tol:
            result.append((sum(group) / len(group), kinds))
            group, kinds = [], set()
        group.append(coord)
        kinds.add(kind)
    result.append((sum(group) / len(group), kinds))
    return result


def _cut_positions(
    columns: list[ColumnCommand], members: list[MemberCommand], direction: str,
) -> list[float]:
    """柱と梁の両方が通る切断位置(柱梁の芯)を方向別に昇順で返す。

    ``direction='X'``(X通り=定 X): 柱の X 座標と、Y 方向に走る梁の中心 X 座標を
    クラスタリングし、柱・梁の両方を含むクラスタの平均を切断位置にする。
    ``direction='Y'``(Y通り=定 Y): 柱の Y 座標と、X 方向に走る梁の中心 Y 座標。
    """
    axis = 0 if direction == 'X' else 1
    tagged: list[tuple[float, str]] = [
        (column['position'][axis], 'column') for column in columns
    ]
    for member in members:
        sx, sy = member['start'][0], member['start'][1]
        ex, ey = member['end'][0], member['end'][1]
        dx, dy = ex - sx, ey - sy
        # X通りは Y 方向に走る梁(|dx| < |dy|)、Y通りは X 方向に走る梁(|dy| < |dx|)。
        runs_y = abs(dx) < abs(dy)
        if (direction == 'X') == runs_y:
            tagged.append(((sx + ex) / 2.0 if axis == 0 else (sy + ey) / 2.0, 'beam'))
    return [
        coord for coord, kinds in _clusters(tagged, CLUSTER_TOL)
        if 'column' in kinds and 'beam' in kinds
    ]


def _name_cuts(
    cuts: list[float], axes: list[tuple[str, float]],
) -> list[str]:
    """切断位置(昇順)を名前付き通り芯に照合して名前を返す。

    一致すれば通り芯名。外れれば中間の通りとして、直前(座標の小さい側)の通り芯を基準に
    数字書式は ``'``、いろは書式は ``又`` で連番する。
    """
    names: list[str] = []
    base_name: str | None = None
    base_coord = float('-inf')
    counter = 0
    for cut in cuts:
        match = next(
            (name for name, coord in axes if abs(coord - cut) <= AXIS_MATCH_TOL),
            None)
        if match is not None:
            base_name, counter = match, 0
            base_coord = next(c for n, c in axes if n == match)
            names.append(match)
            continue
        # 中間の通り: 直前(coord < cut)の通り芯を基準にする
        preceding = [(n, c) for n, c in axes if c < cut - AXIS_MATCH_TOL]
        if preceding:
            prec_name, prec_coord = preceding[-1]
            if prec_coord != base_coord:
                base_name, base_coord, counter = prec_name, prec_coord, 0
        elif base_name is None:
            # 最初の通り芯より手前の中間通り(まれ)。先頭の通り芯を基準にフォールバック。
            if axes:
                base_name, base_coord = axes[0][0], axes[0][1]
        counter += 1
        if base_name is None:
            names.append(f'{counter}')
        elif _is_iroha_name(base_name):
            names.append('又' * counter + base_name)
        else:
            names.append(base_name + "'" * counter)
    return names


def _grid_plan_bounds(
    ifc_file: ifcopenshell.file,
) -> tuple[float, float, float, float] | None:
    """通り芯からセンタリング後の平面 bbox ``(min_x, max_x, min_y, max_y)`` を返す。"""
    lines, center_x, center_y = resolve_lines(ifc_file)
    if not lines:
        return None
    xs = [x for x1, _y1, x2, _y2, _n in lines for x in (x1, x2)]
    ys = [y for _x1, y1, _x2, y2, _n in lines for y in (y1, y2)]
    return (
        min(xs) - center_x, max(xs) - center_x,
        min(ys) - center_y, max(ys) - center_y,
    )


def _commands_for_direction(
    direction: str,
    cuts: list[float],
    axes: list[tuple[str, float]],
    bounds: tuple[float, float, float, float],
) -> list[SectionCommand]:
    """1 方向ぶんの section 命令を組み立てる(既製 20 枚まで)。"""
    min_x, max_x, min_y, max_y = bounds
    names = _name_cuts(cuts, axes)
    commands: list[SectionCommand] = []
    for k, (cut, name) in enumerate(zip(cuts, names), start=1):
        if k > MAX_PER_DIRECTION:
            break
        if direction == 'X':
            # X通り=定 X の鉛直な指示線(Y 方向に延びる)
            line_start = [cut, min_y - SECTION_LINE_MARGIN]
            line_end = [cut, max_y + SECTION_LINE_MARGIN]
        else:
            # Y通り=定 Y の水平な指示線(X 方向に延びる)
            line_start = [min_x - SECTION_LINE_MARGIN, cut]
            line_end = [max_x + SECTION_LINE_MARGIN, cut]
        commands.append({
            'direction': direction,
            'source_number': f'{direction}{k}',
            'drawing_number': name,
            'drawing_title': f'{name}{TITLE_SUFFIX}',
            'line_start': line_start,
            'line_end': line_end,
        })
    return commands


def build_section_commands(
    ifc_file: ifcopenshell.file,
    members: list[MemberCommand],
    columns: list[ColumnCommand],
) -> list[SectionCommand]:
    """軸組図の section 命令のリストを組み立てて返す。

    柱と梁の両方が通る通り(柱梁の芯)を X・Y 方向それぞれ検出し、切断位置の昇順に
    既製ビューポート ``X{k}`` / ``Y{k}`` へ割り当て、切断位置に応じた通りの名前
    (通り芯名 / 中間通りは ``'`` or ``又``)を図番・タイトルにする。通り芯が無い場合は
    平面の広がりを決められないため空リストを返す。
    """
    bounds = _grid_plan_bounds(ifc_file)
    if bounds is None:
        return []
    x_axes, y_axes = _named_axes(ifc_file)
    x_cuts = _cut_positions(columns, members, 'X')
    y_cuts = _cut_positions(columns, members, 'Y')
    return [
        *_commands_for_direction('X', x_cuts, x_axes, bounds),
        *_commands_for_direction('Y', y_cuts, y_axes, bounds),
    ]
