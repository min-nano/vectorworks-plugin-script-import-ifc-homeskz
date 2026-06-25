"""JSON 命令セット(ドキュメント)のスキーマ定義と検証。

命令セットは IFC 解析フェーズ(``ifc`` パッケージ)が生成し、
描画フェーズ(``vw`` パッケージ)が消費する JSON 直列化可能な dict。
このモジュールは vs にも ifcopenshell にも依存しない。

スキーマ (version 5):

    {
        "version": 5,
        "stories": [
            {
                "name": "1階",            # VectorWorks のストーリ名
                "suffix": "1",            # CreateStory の suffix(非空必須)
                "elevation": 473.0,       # ストーリ高さ (mm)
                "levels": [
                    {
                        "type": "FL",         # ストーリレベルタイプ名
                        "offset": 0.0,        # ストーリ基準からのオフセット (mm)
                        "layer": "1-FL"       # 生成するデザインレイヤ名
                    }
                ]
            }
        ],
        "grids": [
            {
                "label": "X1",            # 通り芯の軸名
                "layer": "共通",           # 配置先デザインレイヤ名
                "class": "01作図-...",     # 割り当てるクラス名
                "start": [x1, y1],        # 始点 (mm, センタリング済み)
                "end": [x2, y2]           # 終点 (mm, センタリング済み)
            }
        ],
        "members": [
            {
                "layer": "1-横架材天端",   # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "member_id": "120×180 - 杉...",  # 構造材 ID
                # start/end・elevation/end_elevation は断面の基準点
                # (左右中央・上端 = 天端中央)が通る線を表す。構造材ツールの
                # 断面基準点(左右中央・上端)にそのまま渡せる座標。
                "start": [x1, y1],        # 始点 (mm, センタリング済み)
                "end": [x2, y2],          # 終点 (mm, センタリング済み)
                "width": 120.0,           # 断面幅 (mm)
                "height": 180.0,          # 断面背 (mm)
                "elevation": 425.0,       # 始点の天端 Z 高さ (mm, 絶対値)
                "end_elevation": 425.0    # 終点の天端 Z 高さ (mm, 絶対値)。
                                          # 始点と異なる場合は傾斜梁(登り梁・隅木等)
            }
        ],
        "columns": [
            {
                # 柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描く。
                "layer": "1-柱",          # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                # 構造材 ID。"{幅}×{成} - {種別}" に柱頭・柱脚金物の仕様を
                # 連結した文字列(StructuralMember の MemberID に格納する。
                # 構造材ツールには金物専用フィールドが無いため、金物仕様は
                # MemberID に含めて保持する)。
                "member_id": "105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(ろ)",
                "position": [x, y],       # 配置 XY (mm, センタリング済み)
                "width": 105.0,           # 断面幅 (mm)
                "depth": 105.0,           # 断面成 (mm)
                "height": 2844.0,         # 柱高さ (mm, 鉛直パス長 = 上端 − 下端)
                "elevation": 426.0,       # 柱下端の Z 高さ (mm, 絶対値)
                # 高さ基準(ストーリレベルへのバインド)。柱は構造用途を柱
                # (StructuralUse=4) とし、柱頭/柱脚をストーリレベルに結び付ける。
                # story_offset は柱が乗るストーリ(=レイヤのストーリ)からの相対階数、
                # level はそのストーリのレベル名、offset はレベルからの距離 (mm)。
                # offset は IFC の実ジオメトリ(柱の下端・上端の絶対 Z)とバインド先
                # レベルの絶対 Z の差で決まる。一般階: 始端=自階の横架材天端、終端=
                # 上階の横架材天端 (最上階直下の階では上階=屋根のため軒高)。標準的な
                # 柱は下端が自階天端に一致するため始端 offset≈0、上端は上階梁の下端
                # (上階天端から梁背分下)になるため終端 offset≈ -梁背(負値)。
                # 最上階(屋根): 始端・終端とも自階の軒高基準で、終端は柱上端まで
                # (軒高からの距離=おおむね柱高さ)持ち上げる。
                "start_bound": {"story_offset": 0, "level": "横架材天端", "offset": 0.0},
                "end_bound": {"story_offset": 1, "level": "軒高", "offset": -180.0},
                # 柱頭・柱脚金物の仕様文字列(該当金物が無ければ "")。member_id
                # にも連結されるが、構造化された記録として個別にも保持する。
                "top_hardware": "柱頭金物:(ろ)",    # 柱頭金物の仕様
                "bottom_hardware": "柱脚金物:(ろ)"  # 柱脚金物の仕様
            }
        ]
    }
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

DOCUMENT_VERSION = 6


class LevelCommand(TypedDict):
    """story 命令内の 1 ストーリレベル。"""

    type: str
    offset: float
    layer: str


class StoryCommand(TypedDict):
    """ストーリ・ストーリレベル・デザインレイヤを生成する命令。"""

    name: str
    suffix: str
    elevation: float
    # levels の並び順がデザインレイヤのスタック順(ナビゲーション表示順)になる。
    # 柱レイヤを FL(最上階は軒高)レイヤの直上に置くため柱レベルを先頭にする。
    levels: list[LevelCommand]


# 'class' キーが Python の予約語のため functional 構文で定義する
GridCommand = TypedDict('GridCommand', {
    'label': str,
    'layer': str,
    'class': str,
    'start': list[float],
    'end': list[float],
})
"""通り芯 (GridAxis オブジェクト) を描画する命令。"""


class MemberCommand(TypedDict):
    """構造材 (StructuralMember オブジェクト) を描画する命令。

    start/end と elevation/end_elevation は断面の基準点(左右中央・上端 =
    天端中央)が通る線を表す。elevation と end_elevation が異なる場合は
    傾斜梁(登り梁・隅木等)。
    """

    layer: str
    member_id: str
    start: list[float]
    end: list[float]
    width: float
    height: float
    elevation: float
    end_elevation: float


class StoryBoundCommand(TypedDict):
    """柱の高さ基準(ストーリレベルへのバインド)1 端分。

    story_offset は柱が乗るストーリ(=レイヤのストーリ)からの相対階数
    (0=自階、1=上階)、level はそのストーリのレベル名(横架材天端 / 軒高)、
    offset はレベルからの距離 (mm)。SetObjectStoryBound に渡す。
    """

    story_offset: int
    level: str
    offset: float


class ColumnCommand(TypedDict):
    """柱 (StructuralMember オブジェクト) を鉛直材として描画する命令。

    柱は梁と同じ構造材ツールで描く。下端 (elevation) から高さ (height) 分の
    鉛直パスを持ち、断面は width×depth。member_id は構造材 ID で、柱頭・柱脚
    金物の仕様も連結して保持する(構造材ツールに金物専用フィールドが無いため)。
    高さ基準は start_bound / end_bound でストーリレベルにバインドする(構造用途は
    柱)。position・elevation・height はパスのジオメトリ(XY と初期 Z・長さ)に使う。
    """

    layer: str
    member_id: str
    position: list[float]
    width: float
    depth: float
    height: float
    elevation: float
    start_bound: StoryBoundCommand
    end_bound: StoryBoundCommand
    top_hardware: str
    bottom_hardware: str


class Document(TypedDict):
    """両フェーズを接続する命令セット全体。"""

    version: int
    stories: list[StoryCommand]
    grids: list[GridCommand]
    members: list[MemberCommand]
    columns: list[ColumnCommand]


class DocumentValidationError(ValueError):
    """命令セットがスキーマに適合しない場合に送出される。"""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise DocumentValidationError(message)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_point(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_is_number(c) for c in value)
    )


def _validate_level(index: int, level_index: int, level: Any) -> None:
    where = f'stories[{index}].levels[{level_index}]'
    _require(isinstance(level, dict), f'{where} は dict である必要があります')
    _require(isinstance(level.get('type'), str) and level['type'],
             f'{where}.type は非空文字列である必要があります')
    _require(_is_number(level.get('offset')), f'{where}.offset は数値である必要があります')
    _require(isinstance(level.get('layer'), str) and level['layer'],
             f'{where}.layer は非空文字列である必要があります')


def _validate_story(index: int, command: Any) -> None:
    where = f'stories[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('name'), str) and command['name'],
             f'{where}.name は非空文字列である必要があります')
    # 空文字 suffix は VW 2026 で 2 回目以降の CreateStory が失敗するため不可
    _require(isinstance(command.get('suffix'), str) and command['suffix'],
             f'{where}.suffix は非空文字列である必要があります')
    _require(_is_number(command.get('elevation')),
             f'{where}.elevation は数値である必要があります')
    _require(isinstance(command.get('levels'), list),
             f'{where}.levels はリストである必要があります')
    for j, level in enumerate(command['levels']):
        _validate_level(index, j, level)


def _validate_grid(index: int, command: Any) -> None:
    where = f'grids[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('label'), str),
             f'{where}.label は文字列である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')


def _validate_member(index: int, command: Any) -> None:
    where = f'members[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('member_id'), str),
             f'{where}.member_id は文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')
    for key in ('width', 'height', 'elevation', 'end_elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')


def _validate_column(index: int, command: Any) -> None:
    where = f'columns[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('member_id'), str),
             f'{where}.member_id は文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    for key in ('width', 'depth', 'height', 'elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')
    for key in ('start_bound', 'end_bound'):
        _validate_story_bound(where, key, command.get(key))
    for key in ('top_hardware', 'bottom_hardware'):
        _require(isinstance(command.get(key), str),
                 f'{where}.{key} は文字列である必要があります')


def _validate_story_bound(where: str, key: str, bound: Any) -> None:
    field = f'{where}.{key}'
    _require(isinstance(bound, dict), f'{field} は dict である必要があります')
    _require(isinstance(bound.get('story_offset'), int)
             and not isinstance(bound.get('story_offset'), bool),
             f'{field}.story_offset は整数である必要があります')
    _require(isinstance(bound.get('level'), str) and bound['level'],
             f'{field}.level は非空文字列である必要があります')
    _require(_is_number(bound.get('offset')),
             f'{field}.offset は数値である必要があります')


def validate_document(document: Any) -> Document:
    """命令セットを検証し、不正な場合は DocumentValidationError を送出する。"""
    _require(isinstance(document, dict), '命令セットは dict である必要があります')
    _require(document.get('version') == DOCUMENT_VERSION,
             f'未対応の命令セットバージョンです: {document.get("version")!r}')
    for key in ('stories', 'grids', 'members', 'columns'):
        _require(isinstance(document.get(key), list),
                 f'"{key}" はリストである必要があります')
    for i, command in enumerate(document['stories']):
        _validate_story(i, command)
    for i, command in enumerate(document['grids']):
        _validate_grid(i, command)
    for i, command in enumerate(document['members']):
        _validate_member(i, command)
    for i, command in enumerate(document['columns']):
        _validate_column(i, command)
    try:
        # スキーマ検証だけでは未知キー配下の非直列化値を検出できないため、
        # JSON 直列化可能性も明示的に検証する (NaN/Infinity も拒否)
        json.dumps(document, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise DocumentValidationError(
            f'命令セットは JSON 直列化可能である必要があります: {e}'
        ) from e
    return document
