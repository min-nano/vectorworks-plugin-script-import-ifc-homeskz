"""解析フェーズ (ifc.section) のテスト。vs 非依存。

平面の広がりは通り芯(resolve_lines)から得るため、通り芯解決を monkeypatch で
差し替え、切断線・視線・深さ・鉛直クリップ・シートレイヤ番号の導出を検証する。
"""
from __future__ import annotations

from typing import Any

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    DOCUMENT_VERSION,
    SheetCommand,
    StoryCommand,
    validate_document,
)
from vectorworks_plugin_import_ifc_homeskz.ifc import section

# 通り芯 bbox: 生座標 x∈[0,8000], y∈[0,16000], 中心 (4000,8000)。
# センタリング後は x∈[-4000,4000], y∈[-8000,8000]。
_LINES = [
    (0.0, 0.0, 8000.0, 0.0, 'X1'),
    (0.0, 16000.0, 8000.0, 16000.0, 'X2'),
    (0.0, 0.0, 0.0, 16000.0, 'Y1'),
    (8000.0, 0.0, 8000.0, 16000.0, 'Y2'),
]
_CENTER = (4000.0, 8000.0)

# 通り芯解決(resolve_lines)を monkeypatch するため ifc_file は使われない。
_IFC: Any = None


def _stories() -> list[StoryCommand]:
    return [
        {'name': '基礎', 'suffix': 'F', 'elevation': 0.0, 'levels': []},
        {'name': '1階', 'suffix': '1', 'elevation': 500.0, 'levels': []},
        {'name': '屋根', 'suffix': 'R', 'elevation': 6000.0, 'levels': []},
    ]


def _sheets(numbers: list[str]) -> list[SheetCommand]:
    return [{
        'number': n, 'title': f'図{n}',
        'viewport': {'drawing_title': f'図{n}', 'drawing_number': n,
                     'layers': ['共通']},
    } for n in numbers]


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        section, 'resolve_lines',
        lambda _ifc: (list(_LINES), _CENTER[0], _CENTER[1]))


class TestBuildSectionCommands:
    def test_center_cut_geometry(self, patched: None) -> None:
        commands = section.build_section_commands(_IFC, _stories(), _sheets(['1']))
        assert len(commands) == 1
        cmd = commands[0]
        # 建物中心 X(センタリング後 0)を Y 方向に走る切断線(前後 1000mm 余裕)
        assert cmd['line_start'] == [0.0, -9000.0]
        assert cmd['line_end'] == [0.0, 9000.0]
        # 視線方向は -X 側(切断線中点の高さ)
        assert cmd['look'] == [-1000.0, 0.0]
        # 見込み深さ = X 幅(8000)+ 余裕(2000)
        assert cmd['depth'] == 10000.0
        # 鉛直クリップ = 最小 elevation(0)-1000 〜 最大 elevation(6000)+5000
        assert cmd['start_height'] == -1000.0
        assert cmd['end_height'] == 11000.0
        assert cmd['scale'] == 100.0

    def test_number_follows_last_sheet(self, patched: None) -> None:
        commands = section.build_section_commands(
            _IFC, _stories(), _sheets(['1', '2', '3', '4', '5']))
        assert commands[0]['number'] == '6'
        assert commands[0]['drawing_number'] == '6'

    def test_number_fallback_without_sheets(self, patched: None) -> None:
        commands = section.build_section_commands(_IFC, _stories(), [])
        # 伏図が無い(番号を引けない)場合はフォールバック番号(1 は基礎伏図の予約)
        assert commands[0]['number'] == str(section._SECTION_FALLBACK_NUMBER)

    def test_empty_without_stories(self, patched: None) -> None:
        assert section.build_section_commands(_IFC, [], _sheets(['1'])) == []

    def test_empty_without_grid_lines(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            section, 'resolve_lines', lambda _ifc: ([], 0.0, 0.0))
        assert section.build_section_commands(_IFC, _stories(), _sheets(['1'])) == []

    def test_command_passes_document_validation(self, patched: None) -> None:
        commands = section.build_section_commands(_IFC, _stories(), _sheets(['1']))
        document: dict[str, Any] = {
            'version': DOCUMENT_VERSION,
            'stories': [], 'grids': [], 'members': [], 'rafters': [],
            'roofs': [], 'columns': [], 'walls': [], 'wall_joins': [],
            'slabs': [], 'floors': [], 'anchor_bolts': [], 'floor_posts': [],
            'fire_braces': [], 'joints': [], 'sheets': [],
            'sections': commands, 'tags': [], 'column_marks': [],
            'legends': [], 'rebars': [],
        }
        # 生成した section 命令がスキーマ検証を通ること
        validate_document(document)
