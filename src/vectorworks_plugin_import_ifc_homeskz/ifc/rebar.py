"""基礎の配筋(鉄筋 PIO)の解析と命令の組み立て。vs 非依存。

基礎の各要素にカスタム PIO「鉄筋」(姉妹プロジェクト vectorworks-plugin-rebar)を
配置する rebar 命令を組み立てる。PIO は 3D パスと配筋仕様(モード・鉄筋)から平面線・
3D 鉄筋・断面 2D コンポーネントを自前で描くため、本リポジトリは PIO の配置と
パラメータ設定までを担う(配筋の描画ロジックは持たない)。

分類と配筋モード:

- **立上り(基礎梁、``Name`` が ``基礎梁`` 始まり)→ 梁モード**。断面(壁厚×壁高)の
  梁として、梁天端の中心線を 3D パスに、上下端筋・せん断補強筋を配筋仕様にする。
  配置先は立上りと同じ ``F-立上り`` レイヤ。
- **地中梁(地中梁・部分地中梁、``Name`` に ``地中梁`` を含む)→ 梁モード**。立上りと
  同じ扱い。ただし断面が台形等の任意形状のため、断面のバウンディングボックス
  (水平方向の幅×鉛直方向の高さ)を梁断面の近似として用いる。配置先は地中梁を
  スラブとして描く ``F-底盤`` レイヤ。
- **底盤(基礎底盤・布基礎底盤・独立基礎底盤、``Name`` に ``底盤`` を含む)→ スラブ
  モード**。底盤天端の外形を 3D パス(閉じた多角形)に、主筋・配力筋(シングル・
  両方向)とスラブ厚を配筋仕様にする。配置先は底盤と同じ ``F-底盤`` レイヤ。

配筋仕様は IFC の ``Pset_Reinforcement`` プロパティセット(``TopReinforce`` /
``BottomReinforce`` / ``ShearReinforce``、例 ``SD295_1-D13`` / ``SD295_1-D10@300`` /
底盤は ``SD295_D13@300_D13@300``)から取得し、鋼種(``SD295_`` / ``SD295-``)の接頭辞を
除いて PIO の配筋仕様文字列にする。せん断補強筋は鉄筋 PIO が脚数の接頭辞
(``1-`` 等)で配置を切り替えるため、脚数を常に ``1-``(中央縦筋 1 本)に固定した
``1-D10@200`` 形式にする(ホームズ君の出力は全て縦筋 1 本の前提)。プロパティが無い
(IFC に配筋情報が出力されていない)要素には既定値(立上り・地中梁=上下 1-D13・
せん断 1-D10@250、底盤=D13@150 シングル両方向)を使う。

座標は通り芯・基礎と同じグリッド中心オフセットで補正する。押し出しソリッドの
ワールド変換・断面外形の取得は ``footing.py`` の低レベルヘルパーを再利用する。
"""
from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from ..document import RebarCommand
from .footing import (
    _Solid,
    _footprint,
    _is_base_slab,
    _is_ground_beam,
    _is_wall,
    _iter_footing_elements,
    _world_solid,
    _z_top_and_thickness,
)
from .grid import resolve_lines
from .story import LAYER_FOUNDATION_SLAB, LAYER_FOUNDATION_WALL

if TYPE_CHECKING:
    import ifcopenshell

# 配筋 PIO(鉄筋)本体の描画クラス。PIO は全図形をこのクラスで描くため、立上り・
# 地中梁・底盤の配筋を 1 つのクラスにまとめる(コンクリートの構造クラスとは分け、
# 配筋の線種・色を独立して調整できるようにする)。
CLASS_REBAR = '04構造-01基礎-09鉄筋'

# 配筋情報を保持するプロパティセット名(ホームズ君 IFC)。
PSET_REINFORCEMENT = 'Pset_Reinforcement'
_PROP_TOP = 'TopReinforce'
_PROP_BOTTOM = 'BottomReinforce'
_PROP_SHEAR = 'ShearReinforce'

# IFC に配筋情報が無い場合の既定値(ユーザー指定)。
DEFAULT_BEAM_TOP = '1-D13'
DEFAULT_BEAM_BOTTOM = '1-D13'
DEFAULT_BEAM_STIRRUP = '1-D10@250'
DEFAULT_SLAB_MAIN = 'D13@150'
DEFAULT_SLAB_DIST = 'D13@150'

# 鋼種の接頭辞(例 ``SD295_`` / ``SD295-``)。仕様文字列の先頭からこれを取り除く。
# 先頭が「英字 1〜4 + 数字 + 区切り(``_`` か ``-``)」なら鋼種とみなす。``2-D13`` の
# ように数字始まりは鋼種でないため対象外(先頭が英字でないとマッチしない)。
_GRADE_RE = re.compile(r'^[A-Za-z]{1,4}\d+[_-](.+)$')
# 脚数の接頭辞(``1-`` 等)。鉄筋 PIO の Stirrup はこの脚数で配置を切り替えるが、
# ホームズ君の出力は全て縦筋 1 本のため、脚数を常に ``1-`` に固定する。
_COUNT_PREFIX_RE = re.compile(r'^\d+\s*-\s*')
# せん断補強筋に固定する脚数の接頭辞(縦筋 1 本)。
_SINGLE_LEG_PREFIX = '1-'


def _strip_grade(text: str) -> str:
    """鋼種の接頭辞(``SD295_`` / ``SD295-``)を取り除いた仕様文字列を返す。"""
    match = _GRADE_RE.match(text.strip())
    return match.group(1) if match else text.strip()


def _strip_count_prefix(text: str) -> str:
    """本数の接頭辞(``1-`` 等)を取り除く(``1-D10@300`` → ``D10@300``)。"""
    return _COUNT_PREFIX_RE.sub('', text)


def _force_single_leg(text: str) -> str:
    """せん断補強筋の脚数の接頭辞を ``1-``(縦筋 1 本)に固定する。

    ``1-D10@300`` / ``2-D10@300`` / ``D10@300`` はいずれも ``1-D10@300`` になる
    (ホームズ君の出力は全て縦筋 1 本の前提)。空文字は空のまま返す(既定値に委ねる)。
    """
    spec = _strip_count_prefix(text)
    return f'{_SINGLE_LEG_PREFIX}{spec}' if spec else ''


def _reinforcement_pset(element: ifcopenshell.entity_instance) -> dict[str, str]:
    """要素の ``Pset_Reinforcement`` の文字列プロパティを名前→値の dict で返す。

    プロパティセット(``IfcRelDefinesByProperties``)は IFC2X3・IFC4 とも逆方向属性
    ``IsDefinedBy`` から辿れる。該当プロパティセットが無ければ空 dict。
    """
    for rel in getattr(element, 'IsDefinedBy', None) or []:
        if not rel.is_a('IfcRelDefinesByProperties'):
            continue
        definition = rel.RelatingPropertyDefinition
        if not (definition.is_a('IfcPropertySet')
                and definition.Name == PSET_REINFORCEMENT):
            continue
        result: dict[str, str] = {}
        for prop in definition.HasProperties:
            if prop.is_a('IfcPropertySingleValue') and prop.NominalValue is not None:
                value = prop.NominalValue.wrappedValue
                if isinstance(value, str):
                    result[prop.Name] = value
        return result
    return {}


def _beam_bars(reinf: dict[str, str]) -> tuple[str, str, str]:
    """梁の配筋仕様 dict から (上端筋, 下端筋, せん断補強筋) を返す。

    上下端筋は ``Pset_Reinforcement`` の値から鋼種の接頭辞を除いて PIO 仕様文字列に
    する。せん断補強筋は鋼種を除いたうえで脚数の接頭辞を ``1-``(縦筋 1 本)に固定した
    ``1-D10@200`` 形式にする(ホームズ君の出力は全て縦筋 1 本の前提)。プロパティが無い
    (空)場合は既定値(上下 1-D13・せん断 1-D10@250)を使う。
    """
    top = _strip_grade(reinf.get(_PROP_TOP, '')) or DEFAULT_BEAM_TOP
    bottom = _strip_grade(reinf.get(_PROP_BOTTOM, '')) or DEFAULT_BEAM_BOTTOM
    stirrup = (_force_single_leg(_strip_grade(reinf.get(_PROP_SHEAR, '')))
               or DEFAULT_BEAM_STIRRUP)
    return top, bottom, stirrup


def _slab_bars(reinf: dict[str, str]) -> tuple[str, str]:
    """底盤の配筋仕様 dict から (主筋, 配力筋) を返す。

    ``TopReinforce``(例 ``SD295_D13@300_D13@300``)を 2 方向に分ける。プロパティが
    無い(空・不正)場合は既定値(D13@150 シングル両方向)を使う。
    """
    dirs = _slab_dirs(reinf.get(_PROP_TOP, ''))
    return dirs if dirs is not None else (DEFAULT_SLAB_MAIN, DEFAULT_SLAB_DIST)


def _fmt(value: float) -> str:
    """寸法(mm)を仕様文字列に整形する(整数は末尾の ``.0`` を付けない)。"""
    return f'{value:g}'


def _beam_geometry(
    solid: _Solid, center_x: float, center_y: float,
) -> tuple[list[float], list[float], float, float, float] | None:
    """梁(立上り・地中梁)の断面中心線・断面寸法・天端 Z を返す。

    Returns: ``(始点 [x, y], 終点 [x, y], 幅, 高さ, 天端 Z)``(いずれもセンタリング
    済み・絶対 Z)。中心線は断面の水平中心(プロファイルの u 範囲の中点 = ``lx``
    方向)を通り、押し出し方向に沿う。幅は断面の水平方向(``lx``)の広がり、高さは
    鉛直方向(``ly``)の広がり。矩形断面(立上り)では u 範囲が対称なため中心線は
    配置原点を通り、幅=壁厚・高さ=壁高になる。任意断面(地中梁)ではバウンディング
    ボックスで近似する。退化した(幅・高さ・平面投影長が 0 の)ソリッドは None。
    """
    (origin, lx, _ly, _lz), extrude, depth, pts, _dims = solid
    if not pts:
        return None
    u_vals = [u for u, _v in pts]
    v_vals = [v for _u, v in pts]
    width = max(u_vals) - min(u_vals)
    height = max(v_vals) - min(v_vals)
    u_mid = (min(u_vals) + max(u_vals)) / 2.0
    plan_length = math.hypot(extrude[0], extrude[1]) * depth
    if width <= 0.0 or height <= 0.0 or plan_length <= 0.0:
        return None
    sx = origin[0] + lx[0] * u_mid - center_x
    sy = origin[1] + lx[1] * u_mid - center_y
    ex = sx + extrude[0] * depth
    ey = sy + extrude[1] * depth
    top, _thickness = _z_top_and_thickness(solid)
    return [sx, sy], [ex, ey], width, height, top


def _beam_rebar_command(
    element: ifcopenshell.entity_instance,
    center_x: float,
    center_y: float,
    layer: str,
) -> RebarCommand | None:
    """立上り・地中梁の梁モード rebar 命令を組み立てる。組み立て不能なら None。"""
    solid = _world_solid(element)
    if solid is None:
        return None
    geometry = _beam_geometry(solid, center_x, center_y)
    if geometry is None:
        return None
    start, end, width, height, top = geometry
    top_bars, bottom_bars, stirrup = _beam_bars(_reinforcement_pset(element))
    return {
        'layer': layer,
        'class': CLASS_REBAR,
        'mode': 'beam',
        'closed': False,
        'path': [[start[0], start[1], top], [end[0], end[1], top]],
        'section_size': f'{_fmt(width)}×{_fmt(height)}',
        'top_bars': top_bars,
        'bottom_bars': bottom_bars,
        'stirrup': stirrup,
        'main_bar': '',
        'dist_bar': '',
        'slab_thickness': 0.0,
    }


def _slab_dirs(value: str) -> tuple[str, str] | None:
    """底盤の配筋文字列を主筋・配力筋の 2 方向に分ける。空・不正なら None。

    ``SD295_D13@300_D13@300`` は鋼種を除くと ``D13@300_D13@300`` で、``_`` 区切りの
    2 方向(主筋方向 @ 配力筋方向)。``SD295-D13@200`` のように 1 方向だけのものは
    主筋・配力筋を同じ仕様にする。
    """
    rest = _strip_grade(value)
    parts = [part for part in rest.split('_') if part]
    if not parts:
        return None
    main = parts[0]
    dist = parts[1] if len(parts) > 1 else parts[0]
    return main, dist


def _slab_rebar_command(
    element: ifcopenshell.entity_instance,
    center_x: float,
    center_y: float,
) -> RebarCommand | None:
    """底盤のスラブモード rebar 命令を組み立てる。組み立て不能なら None。"""
    solid = _world_solid(element)
    if solid is None:
        return None
    top, thickness = _z_top_and_thickness(solid)
    boundary = [(x - center_x, y - center_y) for x, y in _footprint(solid)]
    if len(boundary) < 3:
        return None
    main, dist = _slab_bars(_reinforcement_pset(element))
    return {
        'layer': LAYER_FOUNDATION_SLAB,
        'class': CLASS_REBAR,
        'mode': 'slab',
        'closed': True,
        'path': [[x, y, top] for x, y in boundary],
        'section_size': '',
        'top_bars': '',
        'bottom_bars': '',
        'stirrup': '',
        'main_bar': main,
        'dist_bar': dist,
        'slab_thickness': float(round(thickness)),
    }


def build_rebar_commands(ifc_file: ifcopenshell.file) -> list[RebarCommand]:
    """基礎要素から配筋(鉄筋 PIO)の rebar 命令のリストを組み立てる。

    立上り(基礎梁)・地中梁は梁モード、底盤はスラブモードにする。立上りは
    ``F-立上り``、地中梁・底盤は ``F-底盤`` レイヤに配置する(いずれも既存のレイヤに
    重ねる)。組み立て不能な要素(ソリッドが取れない・断面が退化している等)は
    スキップする。

    **梁モードは 1 要素につき 1 本の直線パス(1 本 1 直線)**にする(立上り・地中梁とも
    単一方向の押し出しなので中心線は 2 点の直線になる)。鉄筋 PIO は折れ線の梁だと
    断面ビューポートで横断面と側面図が両方表示されてしまうため、1 本の梁を 1 直線で
    モデル化する運用になっている(vectorworks-plugin-rebar の README 参照)。同一直線上の
    立上りを 1 本にまとめず要素ごとに置くのはこの運用に沿うため(かつ要素ごとに
    Pset_Reinforcement が異なりうるため)。
    """
    _, center_x, center_y = resolve_lines(ifc_file)

    commands: list[RebarCommand] = []
    # 立上り(F-立上り)・地中梁(F-底盤)は梁モード
    for element in ifc_file.by_type('IfcFooting'):
        name = element.Name or ''
        if _is_wall(name):
            command = _beam_rebar_command(
                element, center_x, center_y, LAYER_FOUNDATION_WALL)
        elif _is_ground_beam(name):
            command = _beam_rebar_command(
                element, center_x, center_y, LAYER_FOUNDATION_SLAB)
        else:
            continue
        if command is not None:
            commands.append(command)
    # 底盤(F-底盤)はスラブモード
    for element in _iter_footing_elements(ifc_file):
        if not _is_base_slab(element.Name or ''):
            continue
        command = _slab_rebar_command(element, center_x, center_y)
        if command is not None:
            commands.append(command)
    return commands
