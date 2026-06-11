"""JSON 命令セット（ドキュメント）のスキーマ定義と検証。

命令セットは IFC 解析フェーズ（``ifc`` パッケージ）が生成し、
描画フェーズ（``vw`` パッケージ）が消費する JSON 直列化可能な dict。
このモジュールは vs にも ifcopenshell にも依存しない。

スキーマ (version 1):

    {
        "version": 1,
        "stories": [
            {
                "name": "1階",            # VectorWorks のストーリ名
                "suffix": "1",            # CreateStory の suffix（非空必須）
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
                "layer": "1-横架材天端",   # 配置先デザインレイヤ名（既存のみ・なければスキップ）
                "member_id": "120×180 - 杉...",  # 構造材 ID
                "start": [x1, y1],        # 始点 (mm, センタリング済み)
                "end": [x2, y2],          # 終点 (mm, センタリング済み)
                "width": 120.0,           # 断面幅 (mm)
                "height": 180.0,          # 断面背 (mm)
                "elevation": 425.0        # 配置 Z 高さ (mm, 絶対値)
            }
        ],
        "columns": [
            {
                "layer": "1-横架材天端",   # 配置先デザインレイヤ名（既存のみ・なければスキップ）
                "column_type": "管柱",     # 柱・間柱ツールの種別
                "position": [x, y],       # 配置 XY (mm, センタリング済み)
                "width": 105.0,           # 断面幅 (mm)
                "depth": 105.0,           # 断面成 (mm)
                "height": 2844.0,         # 柱高さ (mm, フォールバック/Height フィールド用)
                "elevation": 426.0,       # 配置 Z 高さ (mm, 絶対値, フォールバック用)
                # 上下端の高さ基準（ストーリレベル基準）。柱・間柱ツールの
                # SetObjectStoryBound に渡し、階高変更に追従させる。
                "bottom_bound": {         # 高さ基準(下): 該当階の横架材天端
                    "story": 0,           # boundStory: 0=当該階, 1=上階, -1=下階
                    "level": "横架材天端",  # layerLevelType (ストーリレベルタイプ名)
                    "offset": 1.0         # そのレベルからのオフセット (mm)
                },
                "top_bound": {            # 高さ基準(上): 上階の横架材天端 or 軒高
                    "story": 1,
                    "level": "横架材天端",
                    "offset": -200.0
                }
            }
        ]
    }
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

DOCUMENT_VERSION = 1


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
    """構造材 (StructuralMember オブジェクト) を描画する命令。"""

    layer: str
    member_id: str
    start: list[float]
    end: list[float]
    width: float
    height: float
    elevation: float


class StoryBound(TypedDict):
    """柱の上端/下端の高さ基準（ストーリレベル基準）。

    VW の SetObjectStoryBound(boundType=2 / Story) に対応する。
    """

    story: int  # boundStory: 0=当該階, 1=上階, -1=下階
    level: str  # layerLevelType (ストーリレベルタイプ名)
    offset: float  # 指定レベルからのオフセット (mm)


class ColumnCommand(TypedDict):
    """柱 (柱・間柱 オブジェクト) を描画する命令。"""

    layer: str
    column_type: str
    position: list[float]
    width: float
    depth: float
    height: float
    elevation: float
    bottom_bound: StoryBound
    top_bound: StoryBound


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
    for key in ('width', 'height', 'elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')


def _validate_story_bound(where: str, bound: Any) -> None:
    _require(isinstance(bound, dict), f'{where} は dict である必要があります')
    _require(isinstance(bound.get('story'), int) and not isinstance(bound.get('story'), bool),
             f'{where}.story は整数である必要があります')
    # boundStory はスキーマ上 -1(下階)/0(当該階)/1(上階) のみ
    _require(bound['story'] in (-1, 0, 1),
             f'{where}.story は -1, 0, 1 のいずれかである必要があります')
    _require(isinstance(bound.get('level'), str) and bound['level'],
             f'{where}.level は非空文字列である必要があります')
    _require(_is_number(bound.get('offset')),
             f'{where}.offset は数値である必要があります')


def _validate_column(index: int, command: Any) -> None:
    where = f'columns[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('column_type'), str) and command['column_type'],
             f'{where}.column_type は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    for key in ('width', 'depth', 'height', 'elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')
    for key in ('bottom_bound', 'top_bound'):
        _require(key in command, f'{where}.{key} は必須です')
        _validate_story_bound(f'{where}.{key}', command[key])


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
