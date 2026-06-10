"""IFC 解析フェーズ (ifc.grid) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.ifc.grid import (
    CLASS_X,
    CLASS_Y,
    TARGET_LAYER,
    build_grid_commands,
    determine_class,
    resolve_lines,
)


def make_ifc_model(*axes: dict[str, Any]) -> ifcopenshell.file:
    """テスト用 ifcopenshell ファイルオブジェクトを生成する。

    axes: ({'name': str, 'points': [(x, y), ...]}, ...)
    """
    ifc = ifcopenshell.file()
    for axis_def in axes:
        pts = [ifc.create_entity('IfcCartesianPoint', Coordinates=list(coords)) for coords in axis_def['points']]
        polyline = ifc.create_entity('IfcPolyline', Points=pts)
        ifc.create_entity('IfcGridAxis', AxisTag=axis_def['name'], AxisCurve=polyline, SameSense=True)
    return ifc


class TestResolveLines:
    def test_resolves_line_coordinates(self) -> None:
        ifc = make_ifc_model(
            {'name': 'Y1', 'points': [(0.0, 0.0), (1000.0, 0.0)]},
            {'name': 'X1', 'points': [(500.0, 0.0), (500.0, 1000.0)]},
        )
        lines, _, _ = resolve_lines(ifc)
        coords = [(x1, y1, x2, y2) for x1, y1, x2, y2, _ in lines]
        assert (0.0, 0.0, 1000.0, 0.0) in coords
        assert (500.0, 0.0, 500.0, 1000.0) in coords

    def test_preserves_axis_name(self) -> None:
        ifc = make_ifc_model(
            {'name': 'Y1', 'points': [(0.0, 0.0), (1000.0, 0.0)]},
            {'name': 'X1', 'points': [(500.0, 0.0), (500.0, 1000.0)]},
        )
        lines, _, _ = resolve_lines(ifc)
        names = {name for *_, name in lines}
        assert 'X1' in names
        assert 'Y1' in names

    def test_deduplicates_identical_lines(self) -> None:
        ifc = make_ifc_model(
            {'name': 'A', 'points': [(0.0, 0.0), (1000.0, 0.0)]},
            {'name': 'B', 'points': [(0.0, 0.0), (1000.0, 0.0)]},
        )
        lines, _, _ = resolve_lines(ifc)
        assert len(lines) == 1

    def test_calculates_center(self) -> None:
        ifc = make_ifc_model(
            {'name': 'Y1', 'points': [(0.0, 0.0), (2000.0, 0.0)]},
            {'name': 'X1', 'points': [(1000.0, -1000.0), (1000.0, 1000.0)]},
        )
        _, center_x, center_y = resolve_lines(ifc)
        assert center_x == pytest.approx(1000.0)
        assert center_y == pytest.approx(0.0)

    def test_returns_zero_center_when_no_axes(self) -> None:
        ifc = ifcopenshell.file()
        lines, center_x, center_y = resolve_lines(ifc)
        assert lines == []
        assert center_x == 0.0
        assert center_y == 0.0

    def test_skips_none_axis_curve(self) -> None:
        axis = MagicMock()
        axis.AxisTag = 'X1'
        axis.AxisCurve = None
        ifc = MagicMock()
        ifc.by_type.return_value = [axis]
        lines, _, _ = resolve_lines(ifc)
        assert lines == []

    def test_skips_non_polyline_curve(self) -> None:
        axis = MagicMock()
        axis.AxisTag = 'X1'
        curve = MagicMock()
        curve.is_a.return_value = False
        axis.AxisCurve = curve
        ifc = MagicMock()
        ifc.by_type.return_value = [axis]
        lines, _, _ = resolve_lines(ifc)
        assert lines == []


class TestDetermineClass:
    def test_x_prefix_uppercase(self) -> None:
        assert determine_class('X1', 0, 0, 0, 1000) == CLASS_X

    def test_x_prefix_lowercase(self) -> None:
        assert determine_class('x2', 0, 0, 0, 1000) == CLASS_X

    def test_y_prefix_uppercase(self) -> None:
        assert determine_class('Y1', 0, 0, 1000, 0) == CLASS_Y

    def test_y_prefix_lowercase(self) -> None:
        assert determine_class('y2', 0, 0, 1000, 0) == CLASS_Y

    def test_vertical_line_becomes_x_class(self) -> None:
        # |Δx| < |Δy| → X通り
        assert determine_class('A', 500, 0, 500, 1000) == CLASS_X

    def test_horizontal_line_becomes_y_class(self) -> None:
        # |Δx| >= |Δy| → Y通り
        assert determine_class('B', 0, 500, 1000, 500) == CLASS_Y

    def test_diagonal_line_follows_dominant_axis(self) -> None:
        # |Δx|=300, |Δy|=1000 → X通り
        assert determine_class('C', 0, 0, 300, 1000) == CLASS_X
        # |Δx|=1000, |Δy|=300 → Y通り
        assert determine_class('D', 0, 0, 1000, 300) == CLASS_Y


class TestBuildGridCommands:
    def test_builds_centered_commands(self) -> None:
        # バウンディングボックス 0..2000 × 0..1000 → 中心 (1000, 500)
        ifc = make_ifc_model(
            {'name': 'Y1', 'points': [(0.0, 0.0), (2000.0, 0.0)]},
            {'name': 'X1', 'points': [(0.0, 0.0), (0.0, 1000.0)]},
        )
        commands = build_grid_commands(ifc)
        assert len(commands) == 2

        by_label = {c['label']: c for c in commands}
        assert by_label['Y1']['start'] == [-1000.0, -500.0]
        assert by_label['Y1']['end'] == [1000.0, -500.0]
        assert by_label['X1']['start'] == [-1000.0, -500.0]
        assert by_label['X1']['end'] == [-1000.0, 500.0]

    def test_assigns_layer_and_class(self) -> None:
        ifc = make_ifc_model(
            {'name': 'Y1', 'points': [(0.0, 0.0), (2000.0, 0.0)]},
            {'name': 'X1', 'points': [(0.0, 0.0), (0.0, 1000.0)]},
        )
        commands = build_grid_commands(ifc)
        by_label = {c['label']: c for c in commands}
        assert by_label['X1']['layer'] == TARGET_LAYER
        assert by_label['X1']['class'] == CLASS_X
        assert by_label['Y1']['class'] == CLASS_Y

    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_grid_commands(ifcopenshell.file()) == []

    def test_commands_are_json_serializable(self) -> None:
        ifc = make_ifc_model(
            {'name': 'X1', 'points': [(0.0, 0.0), (0.0, 1000.0)]},
        )
        commands = build_grid_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
