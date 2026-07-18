"""解析フェーズ (ifc.section) のテスト。vs 非依存。

通り芯解決 (resolve_lines) を monkeypatch し、柱・梁から柱梁の芯(切断位置)を検出し、
名前付き通り芯/中間通りの命名と既製ビューポート (X{k}/Y{k}) への割り当てを検証する。
"""
from __future__ import annotations

from typing import Any

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    DOCUMENT_VERSION,
    validate_document,
)
from vectorworks_plugin_import_ifc_homeskz.ifc import section

# 通り芯(センタリング済み)。X通り(鉛直)= X1/X2/X3、Y通り(水平)= い/ろ。
_LINES = [
    (-4000.0, -3000.0, -4000.0, 3000.0, 'X1'),
    (0.0, -3000.0, 0.0, 3000.0, 'X2'),
    (4000.0, -3000.0, 4000.0, 3000.0, 'X3'),
    (-4000.0, -3000.0, 4000.0, -3000.0, 'い'),
    (-4000.0, 3000.0, 4000.0, 3000.0, 'ろ'),
]

_IFC: Any = None


def _col(x: float, y: float) -> dict[str, Any]:
    return {'position': [x, y]}


def _beam(sx: float, sy: float, ex: float, ey: float) -> dict[str, Any]:
    return {'start': [sx, sy], 'end': [ex, ey]}


# 柱: X1∩い, X2∩い, X2∩ろ, 中間(X=2000,Y=0)
_COLUMNS: list[Any] = [
    _col(-4000.0, -3000.0), _col(0.0, -3000.0),
    _col(0.0, 3000.0), _col(2000.0, 0.0),
]
# 梁: Y 方向(X通り検出用) X=-4000/0/2000、X 方向(Y通り検出用) Y=-3000/0
_MEMBERS: list[Any] = [
    _beam(-4000.0, -3000.0, -4000.0, 3000.0),
    _beam(0.0, -3000.0, 0.0, 3000.0),
    _beam(2000.0, -3000.0, 2000.0, 3000.0),
    _beam(-4000.0, -3000.0, 4000.0, -3000.0),
    _beam(-4000.0, 0.0, 4000.0, 0.0),
]


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        section, 'resolve_lines', lambda _ifc: (list(_LINES), 0.0, 0.0))


class TestBuildSectionCommands:
    def test_detects_and_names_cuts(self, patched: None) -> None:
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        # X 方向: X=-4000(X1), 0(X2), 2000(中間=X2'); Y 方向: Y=-3000(い), 0(中間=又い)
        # Y=3000 は柱のみ(梁なし)なので対象外
        summary = [(c['direction'], c['source_number'], c['drawing_number'])
                   for c in cmds]
        assert summary == [
            ('X', 'X1', 'X1'),
            ('X', 'X2', 'X2'),
            ('X', 'X3', "X2'"),
            ('Y', 'Y1', 'い'),
            ('Y', 'Y2', '又い'),
        ]

    def test_titles_have_suffix(self, patched: None) -> None:
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        assert cmds[0]['drawing_title'] == 'X1通り'
        assert cmds[4]['drawing_title'] == '又い通り'

    def test_x_line_is_vertical_at_cut(self, patched: None) -> None:
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        x1 = cmds[0]
        # X通り: 定 X=-4000 の鉛直線、Y は bbox(-3000..3000)±余白
        assert x1['line_start'] == [-4000.0, -3000.0 - section.SECTION_LINE_MARGIN]
        assert x1['line_end'] == [-4000.0, 3000.0 + section.SECTION_LINE_MARGIN]

    def test_y_line_is_horizontal_at_cut(self, patched: None) -> None:
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        y1 = cmds[3]
        # Y通り: 定 Y=-3000 の水平線、X は bbox(-4000..4000)±余白
        assert y1['line_start'] == [-4000.0 - section.SECTION_LINE_MARGIN, -3000.0]
        assert y1['line_end'] == [4000.0 + section.SECTION_LINE_MARGIN, -3000.0]

    def test_column_only_line_excluded(self, patched: None) -> None:
        # Y=3000 は柱(X2∩ろ)があるが X 方向の梁が無いので対象にならない
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        assert all(c['drawing_number'] != 'ろ' for c in cmds)

    def test_beam_only_line_excluded(self, patched: None) -> None:
        # 梁だけ(柱なし)の通りは対象外
        members: list[Any] = [_beam(1000.0, -3000.0, 1000.0, 3000.0)]  # X=1000 に Y 梁のみ
        cmds = section.build_section_commands(_IFC, members, [])
        assert cmds == []

    def test_empty_without_grid(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(section, 'resolve_lines', lambda _ifc: ([], 0.0, 0.0))
        assert section.build_section_commands(_IFC, _MEMBERS, _COLUMNS) == []

    def test_commands_pass_document_validation(self, patched: None) -> None:
        cmds = section.build_section_commands(_IFC, _MEMBERS, _COLUMNS)
        document: dict[str, Any] = {
            'version': DOCUMENT_VERSION,
            'stories': [], 'grids': [], 'members': [], 'rafters': [],
            'roofs': [], 'columns': [], 'walls': [], 'wall_joins': [],
            'slabs': [], 'floors': [], 'anchor_bolts': [], 'floor_posts': [],
            'fire_braces': [], 'joints': [], 'sheets': [],
            'sections': cmds, 'tags': [], 'column_marks': [],
            'legends': [], 'rebars': [],
        }
        validate_document(document)
