"""描画フェーズの入口 execute_document() のテスト。"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    DOCUMENT_VERSION,
    DocumentValidationError,
)


def _make_stateful_vs_mock() -> MagicMock:
    """ストーリ・レイヤ作成を追跡するステートフルな vs モック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created: set[str] = set()
    template_counter = [0]
    # デザインレイヤを作成順(下→上)で保持し、FLayer/NextLayer/HMoveForward を
    # モデル化する。これがないと reorder_story_layers の走査が終端しない。
    layers: list[str] = []

    def get_obj(name: str) -> object:
        if name in created:
            return 'HANDLE_' + name
        return null_handle

    def create_story(name: str, suffix: str) -> bool:
        created.add(name)
        return True

    def create_layer(name: str, layer_type: int) -> str:
        created.add(name)
        if name not in layers:
            layers.append(name)
        return 'HANDLE_' + name

    def create_level_template(layer_name: str, scale: float, level_type: str,
                              elev: float, wall_h: float) -> tuple[bool, int]:
        idx = template_counter[0]
        template_counter[0] += 1
        # AddLevelFromTemplate はレイヤを自動生成する
        created.add(layer_name)
        if layer_name not in layers:
            layers.append(layer_name)
        return (True, idx)

    def f_layer() -> object:
        return layers[0] if layers else null_handle

    def next_layer(layer_h: Any) -> object:
        if layer_h in layers:
            i = layers.index(layer_h)
            if i + 1 < len(layers):
                return layers[i + 1]
        return null_handle

    def get_layer_by_name(name: str) -> object:
        return name if name in layers else null_handle

    def h_move_forward(layer_h: Any, to_front: bool) -> None:
        if layer_h in layers:
            i = layers.index(layer_h)
            if not to_front and i + 1 < len(layers):
                layers[i], layers[i + 1] = layers[i + 1], layers[i]

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateLevelTemplateN.side_effect = create_level_template
    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.GetLayerByName.side_effect = get_layer_by_name
    vs_mock.HMoveForward.side_effect = h_move_forward
    vs_mock.AddLevelFromTemplate.return_value = True
    vs_mock.GetLayerForStory.return_value = 'HANDLE_template_layer'
    vs_mock.LNewObj.return_value = object()
    vs_mock.CreateCustomObjectPath.return_value = object()
    return vs_mock


def _run_execute_document(vs_mock: MagicMock, document: dict[str, Any]) -> dict[str, int]:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw as vw
        import vectorworks_plugin_import_ifc_homeskz.vw.column as vw_column
        import vectorworks_plugin_import_ifc_homeskz.vw.grid as vw_grid
        import vectorworks_plugin_import_ifc_homeskz.vw.member as vw_member
        import vectorworks_plugin_import_ifc_homeskz.vw.story as vw_story
        importlib.reload(vw_grid)
        importlib.reload(vw_member)
        importlib.reload(vw_story)
        importlib.reload(vw_column)
        importlib.reload(vw)
        return vw.execute_document(document)


def make_document() -> dict[str, Any]:
    # 検証エラー系テストで自由に改変できるよう Document 型ではなく dict として返す
    return {
        'version': DOCUMENT_VERSION,
        'stories': [
            {
                'name': '1階', 'suffix': '1', 'elevation': 473.0,
                'levels': [
                    {'type': '柱', 'offset': -48.0, 'layer': '1-柱'},
                    {'type': 'FL', 'offset': 0.0, 'layer': '1-FL'},
                    {'type': '横架材天端', 'offset': -48.0, 'layer': '1-横架材天端'},
                ],
            },
            {
                'name': '屋根', 'suffix': 'R', 'elevation': 5973.0,
                'levels': [
                    {'type': '軒高', 'offset': 0.0, 'layer': 'R-軒高'},
                ],
            },
        ],
        'grids': [
            {'label': 'X1', 'layer': '共通', 'class': 'X通りクラス',
             'start': [0.0, -1000.0], 'end': [0.0, 1000.0]},
        ],
        'members': [
            {'layer': '1-横架材天端', 'member_id': '120×180',
             'class': '04構造-02木造-01土台-01土台', 'start': [0.0, 0.0],
             'end': [3000.0, 0.0], 'width': 120.0, 'height': 180.0,
             'elevation': 425.0, 'end_elevation': 425.0,
             'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
             'end_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0}},
        ],
        'columns': [
            {'layer': '1-柱', 'member_id': '105×105 - 管柱',
             'class': '04構造-02木造-03柱-02管柱',
             'position': [0.0, 0.0],
             'width': 105.0, 'depth': 105.0, 'height': 2844.0, 'elevation': 426.0,
             'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
             'end_bound': {'story_offset': 1, 'level': '軒高', 'offset': 0.0},
             'top_hardware': '', 'bottom_hardware': ''},
        ],
    }


class TestExecuteDocument:
    def test_executes_all_commands_and_returns_counts(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        counts = _run_execute_document(vs_mock, make_document())
        assert counts == {'stories': 2, 'grids': 1, 'members': 1, 'columns': 1}

    def test_empty_document_returns_zero_counts(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        document = {'version': DOCUMENT_VERSION, 'stories': [], 'grids': [],
                    'members': [], 'columns': []}
        counts = _run_execute_document(vs_mock, document)
        assert counts == {'stories': 0, 'grids': 0, 'members': 0, 'columns': 0}

    def test_rejects_unsupported_version_before_drawing(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        document = make_document()
        document['version'] = 999

        with pytest.raises(DocumentValidationError):
            _run_execute_document(vs_mock, document)

        vs_mock.CreateStory.assert_not_called()
        vs_mock.CreateCustomObjectPath.assert_not_called()

    def test_rejects_invalid_command_before_drawing(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        document = make_document()
        del document['grids'][0]['class']

        with pytest.raises(DocumentValidationError):
            _run_execute_document(vs_mock, document)

        vs_mock.CreateStory.assert_not_called()
